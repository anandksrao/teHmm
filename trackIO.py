#!/usr/bin/env python

#Copyright (C) 2013 by Glenn Hickey
#
#Released under the MIT license, see LICENSE.txt
#!/usr/bin/env python

import os
import sys
import string
import random
import logging
import array
import numpy as np
from pybedtools import BedTool, Interval
from .common import runShellCommand, logger, getLocalTempPath

""" all track-data specific io code goes here.  Just BED implemented for now,
will eventually add WIG and maybe eventually bigbed / bigwig """

###########################################################################

def readTrackData(trackPath, chrom=None, start=None, end=None, **kwargs):
    """ read genome annotation track into python list of values.  a value
    is returned for every element in range (default value is None).  The
    type of file is detected from the extension"""
    data = None
    if not os.path.isfile(trackPath):
        raise RuntimeError("Track file not found %s\n" % trackPath)

    trackExt = os.path.splitext(trackPath)[1]
    tempPath = None
    if trackExt == ".bw" or trackExt == ".bigwig" or trackExt == ".wg" or\
      trackExt == ".bb" or trackExt == "bigbed":
        tempPath = getLocalTempPath("Temp_" + os.path.splitext(
            os.path.basename(trackPath))[0], ".bed")
        logger.info("Extracting %s to temp bed %s. Make sure to erase"
                     " in event of crash" % (trackExt,
                                              os.path.abspath(tempPath)))
        coords = ""
        if chrom is not None:
            assert start is not None and end is not None
            coords = "-chrom=%s -start=%d -end=%d" % (chrom, start ,end)
        tool = "bigWigToBedGraph"
        if trackExt == ".bb" or trackExt == ".bigbed":
            tool = "bigBedToBed"
        runShellCommand("%s %s %s %s" % (tool, trackPath, tempPath, coords))
        trackExt = ".bed"
        trackPath = tempPath
        if (kwargs is None):
            kwargs = dict()
        kwargs["needIntersect"] = False
    if trackExt == ".bed":
        data = readBedData(trackPath, chrom, start, end, **kwargs)
    elif len(trackExt) >= 3 and trackExt[:3].lower() == ".fa":
        data = readFastaData(trackPath, chrom, start, end, **kwargs)
    else:
        sys.stderr.write("Warning: non-BED, non-FASTA file skipped %s\n" %
                         trackPath)
        
    if tempPath is not None:
        runShellCommand("rm -f %s" % tempPath)
    return data

###########################################################################

def readBedData(bedPath, chrom, start, end, **kwargs):
    """ Read a bed file into an array with one entry per base, doing
    name mapping if specified.  
    Returns a list of values.  Note that the buffer used can be passed
    with outBuffer argument"""
    valCol = None
    sort = False
    ignoreBed12 = True
    needIntersect = True
    if kwargs is not None and "valCol" in kwargs:
        valCol = int(kwargs["valCol"])
    valMap = None
    if kwargs is not None and "valMap" in kwargs:
        valMap = kwargs["valMap"]
    defVal = None
    if valMap is not None:
        defVal = valMap.getMissingVal()
    updateMap = False
    if kwargs is not None and "updateValMap" in kwargs:
        updateMap = kwargs["updateValMap"]
    if kwargs is not None and "sort" in kwargs:
        sort = kwargs["sort"] == True
    if kwargs is not None and "ignoreBed12" in kwargs:
        ignoreBed12 = kwargs["ignoreBed12"] == True
    if kwargs is not None and "needIntersect" in kwargs:
        needIntersect = kwargs["needIntersect"]
    useDelta = False
    if kwargs is not None and "useDelta" in kwargs:
        useDelta = kwargs["useDelta"]
    outputBuf = None
    def clamp(x):
        return x
    if kwargs is not None and "outputBuf" in kwargs:
        outputBuf = kwargs["outputBuf"]
        npi = np.iinfo
        if outputBuf.dtype == np.float or outputBuf.dtype == np.float32 \
               or outputBuf.dtype == np.float16:
           npi = np.finfo
        maxVal = npi(outputBuf.dtype).max
        minVal = npi(outputBuf.dtype).min
        def clamp(x):
            if x < minVal or x > maxVal:
                y = min(max(x, minVal), maxVal)
                logger.warning("Clamping track data value %s to %s" % x, y)
                return y
            return x

    if outputBuf is None:
        data = [defVal] * (end - start)
    else:
        data = outputBuf

    logger.debug("readBedData(%s, update=%s)" % (bedPath, updateMap))

    intersectionPath = bedPath
    if needIntersect is True:
        interval = Interval(chrom, start, end)
        logger.debug("intersecting (%s,%d,%d) and %s" % (
            chrom, start, end, bedPath))
        # Below, we try switching from all_hits to intersect()
        # all_hits seems to leak a ton of memory for big files, so
        # we hope intersect (which creates a temp file) will be better
        #intersections = bedTool.all_hits(interval)

        # bedtool intersect still leaking files. comment out
        # and try command-line intersect command instead, removing
        # BedTool entirely from this method
        #tempTool = BedTool(str(interval), from_string = True)
        #intersections = bedTool.intersect(tempTool)
        #tempTool.delete_temporary_history(ask=False)
        #tempTool = None

        tempFileIntIn = getLocalTempPath("Temp_intin", ".bed")
        tempFileIntOut = getLocalTempPath("Temp_intout", ".bed")
        runShellCommand("echo \"%s\" > %s && intersectBed -a %s "
                        "-b %s | sortBed > %s && rm -f %s" % (
                            str(interval), tempFileIntIn, bedPath,
                            tempFileIntIn, tempFileIntOut, tempFileIntIn))
        intersectionPath = tempFileIntOut
    else:
        intersectionPath = bedPath       
        if sort is True:
            logger.debug("sortBed(%s)" % bedPath)
            tempFileSortOut = getLocalTempPath("Temp_sortout", ".bed")
            runShellCommand("sortBed -i %s > %s" % (bedPath, tempFileSortOut))
            intersectionPath = tempFileSortOut
            
    if ignoreBed12 is False:
        logger.debug("bed6(%s)" % bedPath)
        tempFileBed6Out = getLocalTempPath("Temp_b6out", ".bed")
        runShellCommand("bed12ToBed6 -i %s > %s" % (intersectionPath,
                                                    tempFileBed6Out))
        if intersectionPath != bedPath:
            runShellCommand("rm -f %s" % intersectionPath)
        intersectionPath = tempFileBed6Out

    intersections = bedRead(intersectionPath)
    if intersectionPath != bedPath:
        runShellCommand("rm -f %s" % intersectionPath)

    logger.debug("loading data from intersections")
    basesRead = 0
    # prevInterval / prevVal only updated in useDelta mode
    prevInterval = None
    prevVal = 0
        
    for overlap in intersections:
        oStart = max(start, int(overlap[1]))
        oEnd = min(end, int(overlap[2]))
        if valCol is not None:
            if valCol == 0:
                val = 1
            elif valCol == 4:
                assert overlap[4] is not None and overlap[4] != ""
                val = overlap[4]
            else:
                assert valCol == 3
                assert overlap[3] is not None and overlap[3] != ""
                val = overlap[3]
        else:
            val = overlap[3]

        val0 = val
        if useDelta is True:
            if prevInterval is not None and int(overlap[1]) == int(prevInterval[2]) \
              and prevInterval[0] == overlap[0]:
                try: # numeric delta
                    val0 = float(val) - float(prevVal)
                except: # fallback to 0 : same 1 : different
                    val0 = int(val != prevVal)
            prevVal = val
            prevInterval = overlap
            val = 0
        
        if valMap is not None:
            val = valMap.getMap(val, update=updateMap)
            val0 = valMap.getMap(val0, update=updateMap)
    
        data[oStart - start] = val0
        for i in xrange(1, oEnd - oStart):
            data[i + oStart - start] = val
        basesRead += oEnd - oStart            

    logger.debug("done readBedData(%s). %d bases read" % (bedPath, basesRead))

    return data

###########################################################################

def readBedIntervals(bedPath, ncol = 3, 
                     chrom = None, start = None, end = None,
                     sort = False, ignoreBed12 = True):
    """ Read bed intervals from a bed file (or a specifeid range therein).
    NOTE: intervals are sorted by their coordinates"""
    
    if not os.path.isfile(bedPath):
        raise RuntimeError("Bed interval file %s not found" % bedPath)
    assert ncol == 3 or ncol == 4 or ncol == 5
    outIntervals = []
    logger.debug("readBedIntervals(%s)" % bedPath)
    bedTool = BedTool(bedPath)
    if sort is True:
        bedTool = bedTool.sort()
        logger.debug("sortBed(%s)" % bedPath)
    if ignoreBed12 is False:
        bedTool = bedTool.bed6()
        logger.debug("bed6(%s)" % bedPath)
    if chrom is None:
        bedIntervals = bedTool
    else:
        assert start is not None and end is not None
        interval = Interval(chrom, start, end)
        logger.debug("intersecting (%s,%d,%d) and %s" % (chrom, start, end,
                                                          bedPath))
        # Below, we try switching from all_hits to intersect()
        # all_hits seems to leak a ton of memory for big files, so
        # we hope intersect (which creates a temp file) will be better
        #bedIntervals = bedTool.all_hits(interval)
        tempTool = BedTool(str(interval), from_string = True)
        bedIntervals = bedTool.intersect(tempTool)
        tempTool.delete_temporary_history(ask=False)

    logger.debug("appending bed intervals")
    for feat in bedIntervals:
        outInterval = (feat.chrom, feat.start, feat.end)
        if ncol >= 4:
            outInterval += (feat.name,)
        if ncol >= 5:
            outInterval += (feat.score,)
        outIntervals.append(outInterval)
    logger.debug("finished readBedIntervals(%s)" % bedPath)
        
    return outIntervals

###########################################################################

def getMergedBedIntervals(bedPath, ncol=3, sort = False, ignoreBed12 = True):
    """ Merge all contiguous and overlapping intervals""" 

    if not os.path.isfile(bedPath):
        raise RuntimeError("Bed interval file %s not found" % bedPath)
    logger.debug("mergeBedIntervals(%s)" % bedPath)
    outIntervals = []
    bedTool = BedTool(bedPath)
    if sort is True:
        bedTool = bedTool.sort()
        logger.debug("sortBed(%s)" % bedPath)
    if ignoreBed12 is False:
        logger.debug("bed6(%s)" % bedPath)
        bedTool = bedTool.bed6()
    for feat in bedTool.merge():
        outInterval = (feat.chrom, feat.start, feat.end)
        if ncol >= 4:
            outInterval += (feat.name,)
        if ncol >= 5:
            outInterval += (feat.score,)
        outIntervals.append(outInterval)
    logger.debug("finished mergeBedIntervals(%s)" % bedPath)

    return outIntervals

###########################################################################

def writeBedIntervals(intervals, outPath):
    """ write bed intervals to disk """
    outFile = open(outPath, "w")
    for interval in intervals:
        name, score = None, None
        if len(interval) > 3:
            name = str(interval[3])
        if len(interval) > 4:
            score = str(interval[4])
        bi = Interval(interval[0], interval[1], interval[2], name=name,
                      score=score)
        outFile.write(str(bi))    

###########################################################################

def readFastaData(faPath, chrom, start, end, **kwargs):

    valMap = None
    if kwargs is not None and "valMap" in kwargs:
        valMap = kwargs["valMap"]
    defVal = None
    if valMap is not None:
        defVal = valMap.getMissingVal()
    updateMap = False
    if kwargs is not None and "updateValMap" in kwargs:
        updateMap = kwargs["updateValMap"]
    caseSensitive = False
    if kwargs is not None and "caseSensitive" in kwargs:
        caseSensitive = kwargs["caseSensitive"]
    outputBuf = None
    if kwargs is not None and "outputBuf" in kwargs:
        outputBuf = kwargs["outputBuf"]

    if outputBuf is None:
        data = [defVal] * (end - start)
    else:
        data = outputBuf
    logger.debug("readFastaData(%s, update=%s)" % (faPath, updateMap))

    faFile = open(faPath, "r")
    basesRead = 0

    # skip to sequence using readline (faster than fastaRead)
    pos = faFile.tell()
    assert pos == 0
    chromLen = len(chrom) + 1
    while True:
        line = faFile.readline()
        if len(line) == 0 or (line[0] == '>' and line[1:chromLen] == chrom):
            break
        pos = faFile.tell()
    faFile.seek(pos)

    for seqName, seqString in fastaRead(faFile):
        if seqName == chrom:
            for i in xrange(start, end):
                if i >= len(seqString):
                    break
                val = seqString[i]
                if caseSensitive is False:
                    val = val.upper()
                if valMap is not None:
                    val = valMap.getMap(val, update=updateMap)
                data[basesRead] = val
                basesRead += 1
            break
    faFile.close()

    logger.debug("done readFastaData(%s). %d bases read" % (faPath,
                                                             basesRead))
    return data


###########################################################################

# Copied from bioio.py from sonLib (https://github.com/benedictpaten/sonLib):
# Copyright (C) 2006-2012 by Benedict Paten (benedictpaten@gmail.com)
# Released under the MIT license, see LICENSE.txt
def fastaRead(fileHandle):
    """iteratively a sequence for each '>' it encounters, ignores '#' lines
    """
    line = fileHandle.readline()
    while line != '':
        if line[0] == '>':
            name = line[1:-1]
            line = fileHandle.readline()
            seq = array.array('c')
            while line != '' and line[0] != '>':
                if line[0] != '#':
                    seq.extend([ i for i in line[:-1] if i != '\t' and i != ' ' ])
                line = fileHandle.readline()
            for i in seq:
                #For safety and sanity I only allows roman alphabet characters in fasta sequences. 
                if not ((i >= 'A' and i <= 'Z') or (i >= 'a' and i <= 'z') or i == '-'):
                    raise RuntimeError("Invalid FASTA character, ASCII code = \'%d\', found in input sequence %s" % (ord(i), name))
            yield name, seq.tostring()
        else:
            line = fileHandle.readline()

def bedRead(filePath):
    """ pyBedTools leaks files and I can't figure out what to do about it,
    other than just replace it insdead the readBedData loop..."""
    bf = open(filePath, "r")
    intervals = []

    for line in bf:
        if len(line) > 0 and line[0] != "#":
            interval = line[:-1].split("\t")
            if len(interval) > 2:
                intervals.append(interval)

    # man I wish I could figure out just how to close a BedTool?!:
    bf.close()

    return intervals
