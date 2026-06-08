import os
import shlex
import subprocess
from typing import TypeVar, Generic
import shutil
import random
from pathlib import Path
from bisect import bisect_left
import base64

human_names_list = ["alice", "bob", "carol", "dean", "ethan", "felicity", "garreth", "hugh", "illiani", "jace", "kevin", "lance", "marina", "neil", "ondine", "peregrin", "quade", "shane", "tristan", "udelia", "vigo", "waverly", "xavier", "yasmine", "zoe"]

T = TypeVar("T")
class ParetoSampler(Generic[T]):
    def __init__(self, k, arr: list[T]):
        self.k = k
        self.arr = arr
        n = len(arr)
        self.bin_sizes = [self.F_inv(((n-i-1) / (n))) for i in range(n)]
        cumulative_value = 0
        self.cumulated_bins = [0] * n
        for i, x in enumerate(self.bin_sizes):
            cumulative_value += x
            self.cumulated_bins[i] = cumulative_value

    def F_inv(self, x):
        assert x >= 0 and x <= 1
        return (1/(1-x))**(1/self.k)

    def sample_pair(self) -> tuple[T, T]:
        sample1 = random.uniform(0, self.cumulated_bins[-1])
        idx1 = bisect_left(self.cumulated_bins, sample1)
        sample2 = random.uniform(0, self.cumulated_bins[-1] - self.bin_sizes[idx1])
        sample2 = sample2 if idx1 != 0 and sample2 <= self.cumulated_bins[idx1-1] else sample2 + self.bin_sizes[idx1]
        # sample2 | sample1 is uniformly dstributed except that sample2 has an empty slot where index 1 would live
        idx2 = bisect_left(self.cumulated_bins, sample2)
        assert idx1 != idx2
        return self.arr[idx1], self.arr[idx2]

def pformat_commit_id(commit_id: bytes):
    colors = ["\033[90m", "\033[92m", "\033[93m", "\033[94m", "\033[95m", "\033[96m"]
    bgcolors = ["\033[40m", "\033[42m", "\033[43m", "\033[44m", "\033[45m", "\033[46m"]
    h = hash(tuple(commit_id))
    color_idx = h % len(colors)
    color = colors[color_idx]
    bgcolor_idx = h//len(colors) % (len(bgcolors) - 1)
    if bgcolor_idx >= color_idx:
        bgcolor_idx += 1
    bgcolor = bgcolors[bgcolor_idx]
    bold = bcolors.BOLD if h % 2 == 0 else ""
    underline = bcolors.UNDERLINE if h//2 % 2 == 0 else ""
    return color + bgcolor + bold + underline + commit_id[:8].decode() + bcolors.ENDC

def generate_human_names(n) -> list[str]:
    l = len(human_names_list)
    if n <= l:
        return human_names_list[:n]
    
    res = []
    for i in range(n):
        res.append(human_names_list[i % l] + "_" + str(i // l))
    return res

def run_cmd(cmd: str | list[str], cwd: str = ".", env=None) -> bytes:
    if env is None:
        env = os.environ
        if "GIT_DIR" in env:
            del env["GIT_DIR"]
    shell = isinstance(cmd, str)
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, shell=shell)
    res = proc.communicate()[0]
    # if proc.returncode == 1:
    #     return res
    if proc.returncode != 0:
        raise Exception(f"subprocess terminated with non-zero ({proc.returncode}) exit code. cmd:\n{cmd if isinstance(cmd, str) else shlex.join(cmd)}\ncwd: {cwd}")
    return res

def int_to_bytes(x: int) -> bytes:
    return base64.b85encode(int.to_bytes(x, get_size(x)), pad=False)

def get_size(x: int) -> int:
    if x == 0:
        return 1
    return -(int.bit_length(x) // -8)

def int_from_bytes(x: bytes) -> tuple[int, str]:
    """returns the integer parsed from x and whether the input had the correct (minimal) size"""
    try:
        raw = base64.b85decode(x)
    except:
        return 0, f"base85 string not valid: {x}"
    res = int.from_bytes(raw)
    # res = int.from_bytes(x)
    return res, "" if get_size(res) == len(raw) else "not minimal amount of bytes"

def get_some_entry(s: set[T]) -> T:
    """
    Retrieve an arbitrary element from set `s` without removing it from `s`.

    Source - https://stackoverflow.com/a/59841
    Posted by Blair Conrad, modified by community. See post 'Timeline' for change history
    Retrieved 2026-05-27, License - CC BY-SA 3.0
    """
    return next(iter(s))

def validate_hash(hash: str, hashname: str | None = None, throw=True):
    #run_cmd("git fsck --no-reflogs --full --dangling --lost-found", "db")
    # if hashname is None:
    #     hashname = "hash"
    # hash_bytes = hash.encode()
    # if len(hash_bytes) != 40:
    #     msg = f"length of {hashname} {hash} incorrect"
    #     if throw:
    #         raise Exception(msg)
    #     else:
    #         print(msg)
    #     return False
    # for c in hash_bytes:
    #     if not (c >= ord(b'0') and c <= ord(b'9') or c >= ord(b'a') and c <= ord(b'f')):
    #         msg = f"invalid symbol(s) in {hashname} {hash}"
    #         if throw:
    #             raise Exception(msg)
    #         else:
    #             print(msg)
    #         return False
    pass

def ask_if_remove_dir(directory: str) -> bool:
    """Returns True if the directory doesn't exist anymore."""
    if os.path.exists(directory):
        conf = input(f"the directory {directory} exists already. Replace/remove it? [Y/n] ")
        if conf.lower() == "y":
            print(f"deleting directory {directory}")
            shutil.rmtree(directory)
            return True
        else:
            print("aborting")
            return False
    return True

import time
class PerfStatistics:
    def __init__(self, enabled, one_timer: bool =True):
        self.enabled: bool = enabled
        self.one_timer: bool = one_timer
        self.cumulative_times: dict[str, int] = dict()
        self.start_times: dict[str, int] = dict()
        self.remaining_time = 0
        self.remaining_start: None | int = None

    def start(self):
        assert self.remaining_start is None
        self.remaining_start = time.perf_counter_ns()

    def start_timer(self, category):
        if not self.enabled:
            return
        assert not category in self.start_times
        if self.one_timer:
            assert not self.start_times
        t = time.perf_counter_ns()
        if not self.start_times:
            assert self.remaining_start is not None
            self.remaining_time += t - self.remaining_start
            self.remaining_start = None
        self.start_times[category] = t

    def end_timer(self, category):
        if not self.enabled:
            return
        assert category in self.start_times
        t = time.perf_counter_ns()
        self.cumulative_times[category] = t - self.start_times[category] + self.cumulative_times.get(category, 0)
        del self.start_times[category]
        if not self.start_times:
            assert self.remaining_start is None
            self.remaining_start = t
        if self.one_timer:
            assert not self.start_times

    def end(self):
        assert self.remaining_start is not None
        self.remaining_time += time.perf_counter_ns() - self.remaining_start

    def get_times(self):
        res = dict()
        for entry in self.cumulative_times:
            res[entry] = self.cumulative_times[entry] / 1_000_000_000
        res["REMAINING"] = self.remaining_time / 1_000_000_000
        return res

# Source - https://stackoverflow.com/a/287944
# Posted by joeld, modified by community. See post 'Timeline' for change history
# Retrieved 2026-05-04, License - CC BY-SA 4.0

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class CatFileParser():
    """
    instances of this class can be passed to a map module. The upstream
    module is assumed to be a subprocess with the command
    "git cat-file '--batch=%(objectname) %(objectsize)'"

    The output of this function is a list of pairs where the first element is
    the blob id and the second element is the content of the blob or None if
    there is no blob with the id supplied to the parent module (missing blob).
    """
    batch_arg = "--batch=%(objectname) %(objectsize)"
    def __init__(self):
        self.cur_oid: list[int] = []
        self.cur_osize: list[int] = []
        self.cur_content: list[int] = []
        self.in_oid = True
        self.in_osize = False
        self.remaining_content: int = -1

    def __call__(self, data: bytes):
        res: list[tuple[bytes, bytes | None]] = []
        for i in range(len(data)):
            byte = data[i:i+1]
            if self.in_oid:
                assert not self.in_osize
                assert self.remaining_content == -1
                if byte == b" ":
                    self.in_oid = False
                    self.in_osize = True
                elif byte == b"\n":
                    pass
                else:
                    # TODO validate oid
                    self.cur_oid.append(ord(byte))
            elif self.in_osize:
                assert not self.in_oid
                assert self.remaining_content == -1
                if byte == b"\n":
                    self.in_osize = False
                    number_or_missing = bytes(self.cur_osize)
                    # handle missing objects here
                    if number_or_missing == b"missing":
                        oid, _ = self.get_res()
                        res.append((oid, None))
                        # print(f"oid {oid} is missing")
                    else:
                        self.remaining_content = int(number_or_missing)
                        if self.remaining_content == 0:
                            assert not self.in_oid
                            assert not self.in_osize
                            res.append(self.get_res())
                    self.cur_osize = []
                else:
                    self.cur_osize.append(ord(byte))
            elif self.remaining_content > 1:
                self.remaining_content -= 1
                self.cur_content.append(ord(byte))
            else:
                self.cur_content.append(ord(byte))
                assert self.remaining_content == 1
                assert not self.in_oid
                assert not self.in_osize
                res.append(self.get_res())
        return res

    def get_res(self):
        assert not self.in_osize
        res = bytes(self.cur_oid), bytes(self.cur_content)
        self.cur_content = []
        self.cur_osize = []
        self.cur_oid = []
        self.remaining_content = -1
        self.in_oid = True
        return res