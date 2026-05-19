import os
import shlex
import subprocess
from typing import TypeVar, Generic
import shutil
import random
from pathlib import Path
from bisect import bisect_left

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
    shell = isinstance(cmd, str)
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, shell=shell)
    res = proc.communicate()[0]
    # if proc.returncode == 1:
    #     return res
    if proc.returncode != 0:
        raise Exception(f"subprocess terminated with non-zero ({proc.returncode}) exit code. cmd:\n{cmd if isinstance(cmd, str) else shlex.join(cmd)}\ncwd: {cwd}")
    return res

def int_to_bytes(x: int) -> bytes:
    return int.to_bytes(x, get_size(x))

def get_size(x: int) -> int:
    return -(int.bit_length(x) // -8)

def int_from_bytes(x: bytes) -> tuple[int, bool]:
    """returns the integer parsed from x and whether the input had the correct (minimal) size"""
    res = int.from_bytes(x)
    return res, get_size(res) == len(x)

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
    def __init__(self, enabled):
        self.enabled: bool = enabled
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
