#!/usr/bin/env python

#Copyright (C) 2013 by Glenn Hickey
#
#Released under the MIT license, see LICENSE.txt
import unittest
import sys
import os
import argparse
import logging
import random
import numpy as np

from teHmm.track import TrackData
from teHmm.trackIO import readBedIntervals, getMergedBedIntervals
from teHmm.hmm import MultitrackHmm
from teHmm.emission import IndependentMultinomialEmissionModel
from teHmm.emission import PairEmissionModel
from teHmm.track import CategoryMap, BinaryMap
from teHmm.cfg import MultitrackCfg
from teHmm.modelIO import saveModel
from teHmm.common import myLog, EPSILON

def main(argv=None):
    if argv is None:
        argv = sys.argv
        
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Create a teHMM")

    parser.add_argument("tracksInfo", help="Path of Tracks Info file "
                        "containing paths to genome annotation tracks")
    parser.add_argument("trainingBed", help="Path of BED file containing"
                        " elements to train  model on")
    parser.add_argument("outputModel", help="Path of output hmm")
    parser.add_argument("--numStates", help="Number of states in model",
                        type = int, default=2)
    parser.add_argument("--iter", help="Number of EM iterations",
                        type = int, default=100)
    parser.add_argument("--supervised", help="Use name (4th) column of "
                        "<traingingBed> for the true hidden states of the"
                        " model.  Transition parameters will be estimated"
                        " directly from this information rather than EM."
                        " NOTE: The number of states will be determined "
                        "from the bed.",
                        action = "store_true", default = False)
    parser.add_argument("--verbose", help="Print out detailed logging messages",
                        action = "store_true", default = False)
    parser.add_argument("--cfg", help="Use Context Free Grammar insead of "
                        "HMM.  Only works with --supervised for now",
                        action = "store_true", default = False)
    parser.add_argument("--saPrior", help="Confidence in self alignment "
                        "track for CFG.  Probability of pair emission "
                        "is multiplied by this number if the bases are aligned"
                        " and its complement if bases are not aligned. Must"
                        " be between [0,1].", default=0.95, type=float)
    parser.add_argument("--pairStates", help="Comma-separated list of states"
                        " (from trainingBed) that are treated as pair-emitors"
                        " for the CFG", default=None)
    parser.add_argument("--emFac", help="Normalization factor for weighting"
                        " emission probabilities because when there are "
                        "many tracks, the transition probabilities can get "
                        "totally lost. 0 = no normalization. 1 ="
                        " divide by number of tracks.  k = divide by number "
                        "of tracks / k", type=int, default=0)
    parser.add_argument("--initTransProbs", help="Path of text file where each "
                        "line has three entries: FromState ToState Probability"
                        ".  This file (all other transitions get probability 0)"
                        " is used to specifiy the initial transition model.",
                        default = None)
    parser.add_argument("--fixTrans", help="Do not learn transition parameters"
                        " (best used with --initTransProbs)",
                        action="store_true", default=False)
    parser.add_argument("--initEmProbs", help="Path of text file where each "
                        "line has four entries: State Track Symbol Probability"
                        ".  This file (all other emissions get probability 0)"
                        " is used to specifiy the initial emission model.",
                        default = None)
    parser.add_argument("--fixEm", help="Do not learn emission parameters"
                        " (best used with --initEmProbs)",
                        action="store_true", default=False)
    parser.add_argument("--forceTransProbs",
                        help="Path of text file where each "
                        "line has three entries: FromState ToState Probability" 
                        ". These transition probabilities will override any "
                        " learned probabilities after training (unspecified "
                        "will not be set to 0 in this case. the learned values"
                        " will be kept, but normalized as needed" ,
                        default=None)
    parser.add_argument("--forceEmProbs", help="Path of text file where each "
                        "line has four entries: State Track Symbol Probability"
                        ". These "
                        "emission probabilities will override any learned"
                        " probabilities after training (unspecified "
                        "will not be set to 0 in this case. the learned values"
                        " will be kept, but normalized as needed." ,
                        default = None)
     
    args = parser.parse_args()
    if args.cfg is True:
        assert args.supervised is True
        assert args.saPrior >= 0. and args.saPrior <= 1.
    if args.pairStates is not None:
        assert args.cfg is True
    if args.initTransProbs is not None or args.fixTrans is True or\
      args.initEmProbs is not None or args.fixEmission is not None:
        if args.cfg is True:
            raise RuntimeError("--transProbs, --fixTrans, --emProbs, --fixEm "
                               "are not currently compatible with --cfg.")
    if args.fixTrans is True and args.supervised is True:
        raise RuntimeError("--fixTrans option not compatible with --supervised")
    if args.fixEm is True and args.supervised is True:
        raise RuntimeError("--fixEm option not compatible with --supervised")
    if (args.forceTransProbs is not None or args.forceEmProbs is not None) \
      and args.cfg is True:
        raise RuntimeError("--forceTransProbs and --forceEmProbs are not "
                           "currently compatible with --cfg")
        
    if args.verbose is True:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)        

    # read training intervals from the bed file
    logging.info("loading training intervals from %s" % args.trainingBed)
    mergedIntervals = getMergedBedIntervals(args.trainingBed, ncol=4)
    if mergedIntervals is None or len(mergedIntervals) < 1:
        raise RuntimeError("Could not read any intervals from %s" %
                           args.trainingBed)

    # read the tracks, while intersecting them with the training intervals
    logging.info("loading tracks %s" % args.tracksInfo)
    trackData = TrackData()
    trackData.loadTrackData(args.tracksInfo, mergedIntervals)

    catMap = None
    userTrans = None
    if args.supervised is False and args.initTransProbs is not None:
        logging.debug("initializing transition model with user data")
        userTrans, catMap = applyUserTrans(args.initTransProbs)
        # state number is overrided by the transProbs file
        args.numStates = len(catMap)

    truthIntervals = None
    # state number is overrided by the input bed file in supervised mode
    if args.supervised is True:
        logging.info("processing supervised state names")
        # we reload because we don't want to be merging them here
        truthIntervals = readBedIntervals(args.trainingBed, ncol=4)
        catMap = mapStateNames(truthIntervals)
        args.numStates = len(catMap)

    # create the independent emission model
    logging.info("creating emission model")
    numSymbolsPerTrack = trackData.getNumSymbolsPerTrack()
    logging.debug("numSymbolsPerTrack=%s" % numSymbolsPerTrack)
    # only randomize model if 1) using Baum-Welch and 2) have not init values
    randomize = args.supervised is False and args.initEmProbs is None
    emissionModel = IndependentMultinomialEmissionModel(
        args.numStates,
        numSymbolsPerTrack,
        normalizeFac=args.emFac,
        randomize=randomize)

    # initialize the user specified emission probabilities now if necessary
    if args.initEmProbs is not None:
        logging.debug("initializing emission model with user data")
        applyUserEmissions(args.initEmProbs, emissionModel, catMap,
                           trackData.getTrackList())

    # create the model
    if not args.cfg:
        logging.info("creating hmm model")
        model = MultitrackHmm(emissionModel, n_iter=args.iter,
                              state_name_map=catMap, transmat=userTrans,
                              fixTrans = args.fixTrans,
                              fixEmission = args.fixEm)
    else:
        pairEM = PairEmissionModel(emissionModel, [args.saPrior] *
                                   emissionModel.getNumStates())
        assert args.supervised is True
        nestStates = []
        if args.pairStates is not None:
            pairStates = args.pairStates.split(",")
            nestStates = map(lambda x: catMap.getMap(x), pairStates)
        logging.info("Creating cfg model")
        model = MultitrackCfg(emissionModel, pairEM, nestStates,
                              state_name_map=catMap)

    # do the training
    if args.supervised is False:
        logging.info("training via EM")
        model.train(trackData)
    else:
        logging.info("training from input bed states")
        model.supervisedTrain(trackData, truthIntervals)

    # hack user-specified values back in as desired before saving
    if args.forceTransProbs is not None:
        applyUserTrans(model.transmat_, args.forceTransProbs, 
                       model.stateNameMap)
    if args.forceEmProbs is not None:
        stateMap = model.getStateNameMap()
        trackList = model.trackList
        emission = model.getEmissionModel()
        applyUserEmissions(args.forceEmProbs, emission, stateMap, trackList)

    # write the model to a pickle
    logging.info("saving trained model to %s" % args.outputModel)
    saveModel(args.outputModel, model)

###########################################################################
    
def mapStateNames(bedIntervals):
    """ sanitize the states (column 4) of each bed interval, mapping to unique
    integer in place.  return the map"""
    catMap = CategoryMap(reserved=0)
    for idx, interval in enumerate(bedIntervals):
        if len(interval) < 4 or interval[3] is None:
            raise RuntimeError("Could not read state from 4th column" %
                               str(interval))
        bedIntervals[idx] = (interval[0], interval[1], interval[2],
                             catMap.getMap(interval[3], update=True))
    return catMap

###########################################################################

def applyUserTrans(userTransPath, transMap = None, catMap = None):
    """ Modify the transtion probability matrix so that it contains the
    probabilities specified by the given text file.  If a stateNameMap (catMap)
    is provided, it is used (and missing values trigger errors).  If the map
    is None, then one is created.  If the transmap is None, one is created
    as well (with default values being flat distribution.
    The modified transMat and catMap are returned as a tuple, can can be
    applied to the hmm."""
    logging.debug("Applying user transitions to supervised trained HMM")
    
    # first pass just to count the states
    if catMap is None:
        catMap = CategoryMap(reserved=0)
        f = open(userTransPath, "r")
        for line in f:
            if len(line.lstrip()) > 0 and line.lstrip()[0] is not "#":
                toks = line.split()
                assert len(toks) == 3
                float(toks[2])
                catMap.getMap(toks[0], update=True)
                catMap.getMap(toks[1], update=True)
        f.close()

    N = len(catMap)
    mask = np.zeros((N, N), dtype=np.int8)

    # init the transmap if ncessary
    transMat = 1. / float(N) + np.zeros((N, N), dtype=np.float)

    # 2nd pass to read the probabilities into the transmap
    f = open(userTransPath, "r")    
    for line in f:
        if len(line.lstrip()) > 0 and line.lstrip()[0] is not "#":
            toks = line.split()
            assert len(toks) == 3
            prob = float(toks[2])
            fromState = toks[0]
            toState = toks[1]
            if not catMap.has(fromState) or not catMap.has(toState):
                raise RuntimeError("Cannot apply transition %s->%s to model"
                                   " since at least one of the states was not "
                                   "found in the supervised data." % (fromState,
                                                                      toState))
            fid = catMap.getMap(fromState)
            tid = catMap.getMap(toState)
            # remember that this is a user transition
            mask[fid, tid] = 1
            # set the trnasition probability in the matrix
            transMat[fid, tid] = prob

    # normalize all other probabilities (ie that are unmaksed) so that they
    # add up.
    for fid in xrange(N):
        # total probability of learned states
        curTotal = 0.0
        # total probability of learned states after normalization
        tgtTotal = 1.0
        for tid in xrange(N):
            if mask[fid, tid] == 1:
                tgtTotal -= transMat[fid, tid]
            else:
                curTotal += transMat[fid, tid]
        if tgtTotal < -EPSILON:
            raise RuntimeError("User defined probability %f from state %s "
                               "exceeds 1" % (tgtTotal, catMap.getMapBack(fid)))
        for tid in xrange(N):
            if mask[fid, tid] == 0:
                if tgtTotal == 0.:
                    transMat[fid, tid] = 0.
                else:
                    transMat[fid, tid] *= (tgtTotal / curTotal)

    f.close()

    return (transMat, catMap)
    
###########################################################################
    
def applyUserEmissions(userEmPath, emission, stateMap, trackList):
    """ modify a HMM that was constructed using supervisedTrain() so that
    it contains the emission probabilities specified in the userEmPath File."""
    logging.debug("Applying user emissions to supervised trained HMM")
    f = open(userEmPath, "r")
    logProbs = emission.getLogProbs()
    mask = np.zeros(logProbs.shape, dtype=np.int8)

    # scan file and set values in logProbs matrix
    for line in f:
        if len(line.lstrip()) > 0 and line.lstrip()[0] is not "#":
            toks = line.split()
            assert len(toks) == 4
            stateName = toks[0]
            trackName = toks[1]
            symbolName = toks[2]
            prob = float(toks[3])
            if not stateMap.has(stateName):
                raise RuntimeError("State %s not found in supervised data" %
                                   stateName)
            state = stateMap.getMap(stateName)
            track = trackList.getTrackByName(trackName)
            if track is None:
                raise RuntimeError("Track %s not found in supervised data" %
                                   trackName)
            symbolMap = track.getValueMap()
            track = track.getNumber()
            if isinstance(symbolMap, BinaryMap):
                # hack in conversion for binary data, where map expects either
                # None or non-None
                if symbolName == "0" or symbolName == "None":
                    symbolName = None
            elif not symbolMap.has(symbolName):
                sys.stderr.write("Warning: Track %s Symbol %s not found in"
                                 "data (setting as null value)\n" %
                                 (trackName, symbolName))
            symbol = symbolMap.getMap(symbolName)
            assert symbol in emission.getTrackSymbols(track)
            logProbs[track, state, symbol] = myLog(prob)
            mask[track, state, symbol] = 1

    # easier to work outside log space
    probs = np.exp(logProbs)
    
    # normalize all other probabilities (ie that are unmaksed) so that they
    # add up.
    for track in xrange(emission.getNumTracks()):
        for state in xrange(emission.getNumStates()):
            # total probability of learned states
            curTotal = 0.0
            # total probability of learned states after normalization
            tgtTotal = 1.0            
            for symbol in emission.getTrackSymbols(track):
                if mask[track, state, symbol] == 1:
                    tgtTotal -= probs[track, state, symbol]
                else:
                    curTotal += probs[track, state, symbol]
                if tgtTotal < 0.:
                    raise RuntimeError("User defined probability from state %s"
                                       " for track %s exceeds 1" %
                                       (stateMap.getMapBack(state),
                                        symbolMap.getMapBack(symbol)))

            # same correction as applyUserTransmissions()....
            for symbol in emission.getTrackSymbols(track):
                if mask[track, state, symbol] == 0:
                    if tgtTotal == 0.:
                        probs[track, state, symbol] = 0.
                    else:
                        probs[track, state, symbol] *= (tgtTotal / curTotal)

    # Make sure we set our new log probs back into object
    emission.logProbs = myLog(probs)
    
    emission.validate()
    
    f.close()

if __name__ == "__main__":
    sys.exit(main())

    
