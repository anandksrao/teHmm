#!/usr/bin/env python

#Copyright (C) 2013 by Glenn Hickey
#
#Released under the MIT license, see LICENSE.txt
import unittest
import sys
import os
import argparse

from teHmm.tracksInfo import TracksInfo
from teHmm.teHmmModel import TEHMMModel


def main(argv=None):
    if argv is None:
        argv = sys.argv

    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Create a teHMM")

    parser.add_argument("tracksInfo", help="Path of Tracks Info file "
                        "containing paths to genome annotation tracks")
    parser.add_argument("outputModel", help="Path of output hmm")
    parser.add_argument("trainingBed", help="Path of BED file containing elements to train"
                        " model on")
    parser.add_argument("--numStates", help="Number of states in model",
                        type = int, default=2)
    parser.add_argument("--iter", help="Number of EM iterations",
                        type = int, default=1000)
    
    args = parser.parse_args()

    hmmModel = TEHMMModel()
    hmmModel.initTracks(args.tracksInfo)
    hmmModel.loadMultipleTrackData(args.tracksInfo, args.trainingBed, True)
    hmmModel.create(args.numStates, args.iter)
    hmmModel.train()
    hmmModel.save(args.outputModel)
    
if __name__ == "__main__":
    sys.exit(main())
