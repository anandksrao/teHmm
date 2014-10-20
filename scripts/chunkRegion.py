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
Cut up some bed intervals (probably have already written this somewhere else
"""

def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Cut up some bed intervals (probably have already "
        "written this somewhere elsee")
    parser.add_argument("inBed", help="Input bed file")
    parser.add_argument("chunk", help="Chunk size", type=int)
    wiggle = 0.5
    
    args = parser.parse_args()
    assert os.path.exists(args.inBed)

    for interval in BedTool(args.inBed):
        length = interval.end - interval.start
        if length <= args.chunk:
            sys.stdout.write(str(interval))
        else:
            numChunks = int(length / args.chunk)
            if float(length % args.chunk) / float(args.chunk) > wiggle:
                numChunks += 1
            chunkSize = int(length / numChunks)
            for i in xrange(numChunks):
                outInterval = copy.deepcopy(interval)
                outInterval.start = interval.start + chunkSize * i
                if i < numChunks - 1:
                    outInterval.end = outInterval.start + chunkSize
                sys.stdout.write(str(outInterval))
            
if __name__ == "__main__":
    sys.exit(main())