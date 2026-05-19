import argparse
from pathlib import Path
import os
import csv
import matplotlib.pyplot as plt
import numpy as np

import matplotlib as mpl

mpl.rcParams['axes.linewidth'] = 0.1

def main():
    parser = argparse.ArgumentParser(prog="visualize_benchmarks", description="Visualize benchmark results created with run_benchmarks")
    parser.add_argument("-o", "--output-dir", help="specify output directory for visualizations", default=None)
    parser.add_argument("benches", nargs="*", help="specify what benchmarks to visualize")
    args = parser.parse_args()
    specified_tests = args.benches
    output_dir = args.output_dir
    run_all_tests = False
    if len(specified_tests) == 0:
        run_all_tests = True
    testcase_dir = Path("./benchmarks")
    if output_dir is None:
        output_dir = testcase_dir
    for test_dir in os.listdir(testcase_dir):
        if not run_all_tests:
            if test_dir not in specified_tests:
                continue
            else:
                specified_tests.remove(test_dir)
        test_dir_full = testcase_dir / test_dir
        output_dir_full = output_dir / test_dir
        print(test_dir_full)
        assert os.path.isdir(test_dir_full)
        print(f"visualizing benchmark '{test_dir}':")
        stat_dict = dict()
        benchmark_names = []
        with open(test_dir_full/"perf.csv") as file:
            r = csv.DictReader(file)
            for row in r:
                benchmark_names.append(row["NAME"])
                for label in row:
                    if label == "NAME":
                        continue
                    stat_dict[label] = stat_dict.get(label, []) + [float(row[label])]
        fig, ax = plt.subplots()
        bottom = np.zeros(len(benchmark_names))

        for label, times in stat_dict.items():
            if label == "REMAINING":
                continue
            p = ax.bar(benchmark_names, times, 0.5, label=label, bottom=(bottom))
            bottom += np.array(times)
        p = ax.bar(benchmark_names, stat_dict["REMAINING"], 0.5, label="REMAINING", bottom=(bottom))

        ax.set_title(test_dir)
        ax.legend(loc="upper left")

        plt.savefig(output_dir_full / "plot.pdf", format="pdf")
        plt.show()


