import argparse
from pathlib import Path
import os
import csv
import matplotlib.pyplot as plt
from matplotlib.transforms import Bbox
import numpy as np
import glob

import matplotlib as mpl

mpl.rcParams['axes.linewidth'] = 0.1

def main():
    parser = argparse.ArgumentParser(prog="visualize_benchmarks", description="Visualize benchmark results created with run_benchmarks")
    parser.add_argument("-o", "--output-dir", help="specify output directory for visualizations", default=None)
    parser.add_argument("-p", "--stat-prefix", help="specify prefix(es) to visualize", default=None, nargs="+")
    parser.add_argument("benches", nargs="*", help="specify what benchmarks to visualize")
    args = parser.parse_args()
    stat_prefix = args.stat_prefix
    specified_tests = args.benches
    testcase_dir = Path("./benchmarks")
    if args.output_dir is None:
        output_dir = testcase_dir
    else:
        output_dir = Path(args.output_dir)
    run_all_tests = False
    if len(specified_tests) == 0:
        run_all_tests = True
    visualize_all_prefixes = False
    if stat_prefix is None:
        visualize_all_prefixes = True
    for test_dir in os.listdir(testcase_dir):
        if not run_all_tests:
            if test_dir not in specified_tests:
                continue
            else:
                specified_tests.remove(test_dir)
        test_dir_full = testcase_dir / test_dir
        output_dir_full = output_dir / test_dir
        for file in glob.glob(str(output_dir_full) + "**/*.pdf"):
            print(f"removing: {file}")
            os.remove(file)
        print(test_dir_full)
        assert os.path.isdir(test_dir_full)
        print(f"visualizing benchmark '{test_dir}':")
        max_time = 0
        stat_dicts: list[dict] = []
        benchmark_namess: list[list[str]] = []
        file_prefixes: list[str] = []
        for file in glob.glob(str(test_dir_full/"*perf.csv")):
            file_prefix = file.removeprefix(str(test_dir_full/"")).removesuffix("perf.csv")[1:]
            if not (visualize_all_prefixes or file_prefix in stat_prefix):
                continue
            stat_dict = dict()
            benchmark_names = []
            with open(file) as f:
                r = csv.DictReader(f)
                for row in r:
                    benchmark_names.append(row["NAME"])
                    for label in sorted(row):
                        if label == "NAME":
                            continue
                        stat_dict[label] = stat_dict.get(label, []) + [float(row[label])]
            stat_dicts.append(stat_dict)
            benchmark_namess.append(benchmark_names)
            file_prefixes.append(file_prefix)

            bottom = np.zeros(len(benchmark_names))

            for label, times in stat_dict.items():
                if label == "REMAINING":
                    continue
                bottom += np.array(times)

            max_time_from_this_category = bottom.max()

            assert isinstance(max_time_from_this_category, float)

            if max_time < max_time_from_this_category:
                max_time = max_time_from_this_category

        for benchmark_names, stat_dict, file_prefix in zip(benchmark_namess, stat_dicts, file_prefixes):
            fig, ax = plt.subplots(figsize=(7,6))
            ax.set_ylim(ymax=max_time*1.05)
            ax.set_xmargin(0.15)
            bottom = np.zeros(len(benchmark_names))

            for label, times in stat_dict.items():
                if label == "REMAINING":
                    continue
                p = ax.bar(benchmark_names, times, 0.5, label=label, bottom=(bottom))
                for i, val in enumerate(times):
                    if val < max_time * 0.02:
                        continue
                    ax.text(i, bottom[i] + val / 2, f"{val:.3}", va='center', ha='center')
                bottom += np.array(times)
            p = ax.bar(benchmark_names, stat_dict["REMAINING"], 0.5, label="remaining", bottom=(bottom))
            for i, val in enumerate(stat_dict["REMAINING"]):
                time = y=bottom[i] + val
                ax.text(i, time, f"{time:.3}", fontdict=None, va='bottom', ha='center')

            ax.set_title(test_dir)
            ax.set_xlabel("Number of Commits")
            ax.set_ylabel("Runtime (s)")
            ax.legend(loc="upper left")

            os.makedirs(output_dir_full, exist_ok=True)
            fig_file = output_dir_full / (file_prefix + "plot.pdf")
            plt.savefig(fig_file, format="pdf")
            print(f"saved figure to {fig_file}")
            #plt.show()


