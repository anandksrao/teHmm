#!/usr/bin/env python

#Copyright (C) 2014 by Glenn Hickey
#
#Released under the MIT license, see LICENSE.txt
import unittest
import sys
import os
import argparse
import logging
import random
import numpy as np
import time

from teHmm.hmm import MultitrackHmm
from teHmm.common import myLog, EPSILON, initBedTool, cleanBedTool
from teHmm.basehmm import BaseHMM
from teHmm.hmm import MultitrackHmm

""" This is a script to benchmark the HMM dynamic programming functions
(forward, backward and viterbi).  It seems the original scikit implementations
are slower than they need to be.  This script is a sandbox for some tests to
help judge if changes made to the dynamic programming help, without resorting
to using teHmmTrain and teHmmEval which need to load the xml data tracks..
"""
def main(argv=None):
    if argv is None:
        argv = sys.argv
        
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Benchmark HMM Dynamic Programming Functions.")

    parser.add_argument("--N", help="Number of observations.",
                        type=int, default=200000)
    parser.add_argument("--S", help="Number of states.",
                        type=int, default=10)
    parser.add_argument("--alg", help="Algorithm. Valid options are"
                        " {viterbi, forward, backward}.", default="viterbi")
    parser.add_argument("--new", help="Only run new hmm", action="store_true",
                        default=False)
    parser.add_argument("--old", help="Only run old hmm", action="store_true",
                        default=False)
    
    args = parser.parse_args()
    alg = args.alg.lower()
    assert alg == "viterbi" or alg == "forward" or alg == "backward"

    # orginal, scikit hmm
    basehmm = BaseHMM()
    # new, hopefully faster hmm
    mthmm = MultitrackHmm()
    frame = makeFrame(args.S, args.N)
    baseret = None
    mtret = None

    if args.new == args.old or args.old:
        startTime = time.time()
        baseret = runTest(basehmm, frame, alg)
        deltaTime = time.time() - startTime
        print "Elapsed time for OLD %d x %d %s: %s" % (args.N, args.S, args.alg,
                                                       str(deltaTime))    
    if args.new == args.old or args.new:
        startTime = time.time()
        newret = runTest(mthmm, frame, alg)
        deltaTime = time.time() - startTime
        print "Elapsed time for NEW %d x %d %s: %s" % (args.N, args.S, args.alg,
                                                       str(deltaTime))
    if baseret is not None and mtret is not None:
        # note comparison doesnt mean much since data is so boring so 
        # hopefully hmmTest will be more meaningful.  that said, this will still
        # detect many catastrophic bugs. 
        if alg == "viterbi":
            assert_array_almost_eqal(baseret[0], mtret[0])
            assert_array_eqal(baseret[1], mtret[1])
        else:
            assert_array_almost_equal(baseret, mtret)

    
def makeFrame(numStates, numObs, prob=0.5):
    """ Make a dummy framelogprob matrix that the functions execpt"""
    return np.log(prob) + np.zeros((numObs, numStates),)

def runTest(hmm, frame, alg):
    """ call the basehmms low level dp algorithm """
    if alg == "viterbi":
        return hmm._do_viterbi_pass(frame)
    elif alg == "forward":
        return hmm._do_forward_pass(frame)
    elif alg == "backward":
        return hmm._do_backward_pass(frame)
    else:
        assert False

if __name__ == "__main__":
    sys.exit(main())

    
