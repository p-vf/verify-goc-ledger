import os
import shlex
import subprocess
from typing import Tuple

human_names_list = ["alice", "bob", "carol", "dean", "ethan", "felicity", "garreth", "hugh", "illiani", "jace", "kevin", "lance", "marina", "neil", "ondine", "peregrin", "quade", "shane", "tristan", "udelia", "vigo", "waverly", "xavier", "yasmine", "zoe"]

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

def int_from_bytes(x: bytes) -> Tuple[int, bool]:
    """returns the integer parsed from x and whether the input had the correct (minimal) size"""
    res = int.from_bytes(x)
    return res, get_size(res) == len(x)

def validate_hash(hash: str, hashname: str | None = None, throw=True):
    #run_cmd("git fsck --no-reflogs --full --dangling --lost-found", "db")
    if hashname is None:
        hashname = "hash"
    hash_bytes = hash.encode()
    if len(hash_bytes) != 40:
        msg = f"length of {hashname} {hash} incorrect"
        if throw:
            raise Exception(msg)
        else:
            print(msg)
        return False
    for c in hash_bytes:
        if not (c >= ord(b'0') and c <= ord(b'9') or c >= ord(b'a') and c <= ord(b'f')):
            msg = f"invalid symbol(s) in {hashname} {hash}"
            if throw:
                raise Exception(msg)
            else:
                print(msg)
            return False