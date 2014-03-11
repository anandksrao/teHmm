#!/usr/bin/env python

#Copyright (C) 2014 by Glenn Hickey
#
#Released under the MIT license, see LICENSE.txt
import sys
import os
import argparse
import copy

from pybedtools import BedTool, Interval

"""
Stick a bed interval between pairs of lastz termini.  Script written to be used
in conjunction with tsdFinder.py:
lastz termini -> fill termini -> bed input (which gets merged up automatically)
for tsdFinder.py.  Example:

scaffold_1	141	225	1+	43	+
scaffold_1	4479	4563	1+	43	+

becomes

scaffold_1	141	225	1+	43	+
scaffold_1	225	4479	1+	43	+
scaffold_1	4479	4563	1+	43	+

Note: also works on output of cleanTermini.
"""

def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Add interval between pairs of candidate termini, ex as "
        "output by cleanTermini.py")
    parser.add_argument("inBed", help="bed with ltr results to process")
    parser.add_argument("outBed", help="bed to write output to.")
    
    args = parser.parse_args()
    assert os.path.exists(args.inBed)
    outFile = open(args.outBed, "w")

    seen = dict()
    for interval in BedTool(args.inBed).sort():

        # Right termini
        if interval.name in seen:
            prevInterval = seen[interval.name]
            seen.remove(interval.name)
            fillInterval = copy.deepcopy(prevInterval)
            fillInterval.start = min(prevInterval.end, interval.end)
            fillInterval.end = max(prevInterval.start, interval.start)
            outFile.write(str(prevInterval))
            if fillInterval.start >= fillInterval.end:
                sys.stderr.write("No fill written for overlapping intervals\n%s%s" % (
                    prevInterval, interval))
            else:
                outFile.write(str(fillInterval))
            outFile.write(str(interval))            
            
            if args.leaveName is False:
                interval.name = "R_Term"
            left = False

        # Left termini
        else:
            seen[interval.name] = interval
            
    outFile.close()
        
if __name__ == "__main__":
    sys.exit(main())
