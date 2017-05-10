#!/usr/bin/env python
# -*- coding: utf-8 -*-

from scipy import stats

import pysam
import numpy as np


def get_mismatches(bam_file, read_length):
    """Get substitution and indel rate for reads mapped to a reference genome.

    Arguments:
        bam_file (:obj:`str`): input bam file
        read_length (:obj"`int`): length of the mapped reads
    Returns:
        dict: for each nucleotide (keys) the values are a tuple containing the
        choices and probabilties of transiting to another nucleotide.
    """
    array_f = np.zeros([read_length, 24])
    array_r = np.zeros([read_length, 24])
    nucl_choices_f = []
    nucl_choices_r = []
    indels_f = []
    indels_r = []

    dispatch_dict = {
        'AA': 0,
        'aT': 1,
        'aG': 2,
        'aC': 3,
        'TT': 4,
        'tA': 5,
        'tG': 6,
        'tC': 7,
        'CC': 8,
        'cA': 9,
        'cT': 10,
        'cG': 11,
        'GG': 12,
        'gA': 13,
        'gT': 14,
        'gC': 15
    }

    with pysam.AlignmentFile(bam_file, "rb") as bam:
        for read in bam.fetch():
            if not read.is_unmapped:
                # alignment is a list of tuples: aligned read (query) and
                # reference positions. the parameter with_seq adds the ref
                # sequence as the 3rd element of the tuples.
                # substitutions are lower-case.
                alignment = read.get_aligned_pairs(
                    matches_only=True,
                    with_seq=True
                    )
                has_indels = False
                for base in alignment:
                    if read.seq[base[0]] != 'N':  # let's not deal with Ns
                        query_pos = base[0]
                        query_base = read.seq[query_pos]
                        ref_base = base[2]
                        dispatch_key = ref_base + query_base
                        if (query_base.casefold() != ref_base.casefold()
                                and ref_base.isupper()):
                            # flag reads that have one or more indels
                            has_indels = True
                        if read.is_read1 and has_indels is False:
                            array_f[
                                query_pos,
                                dispatch_dict[dispatch_key]] += 1
                        elif read.is_read2 and has_indels is False:
                            array_r[
                                query_pos,
                                dispatch_dict[dispatch_key]] += 1
                # once we've counted the substitutions, we count the indels
                # looking at the cigar
                if has_indels == 1:
                    position = 0
                    for (cigar_type, cigar_length) in read.cigartuples:
                        if cigar_type == 0:  # match
                            position += cigar_length
                        elif cigar_type == 1:  # insertion
                            dispatch_key = ref_base.upper() + '1'
                            if read.is_read1:
                                array_f[
                                    position,
                                    dispatch_dict[dispatch_key]] += 1
                            elif read.is_read2:
                                array_r[
                                    position,
                                    dispatch_dict[dispatch_key]] += 1
                            position += cigar_length
                        elif cigar_type == 2:  # deletion
                            dispatch_key = ref_base.upper() + '2'
                            if read.is_read1:
                                array_f[
                                    position,
                                    dispatch_dict[dispatch_key]] += 1
                            elif read.is_read2:
                                array_r[
                                    position,
                                    dispatch_dict[dispatch_key]] += 1
                            position += cigar_length
                        else:
                            print('error')

    for position in range(read_length):
        nucl_choices_f.append(subst_matrix_to_choices(array_f[position]))
        nucl_choices_r.append(subst_matrix_to_choices(array_r[position]))
        indels_f.append(indel_rate(array_f[position]))
        indels_r.append(indel_rate(array_r[position]))

    return nucl_choices_f, nucl_choices_r, indels_f, indels_r


def subst_matrix_to_choices(mismatches_array):
    """from the raw mismatches at one position, returns nucleotides
    and probabilties of state change (substitutions)"""
    sums = {
        'A': np.sum(mismatches_array[1:4]),
        'T': np.sum(mismatches_array[5:8]),
        'C': np.sum(mismatches_array[9:12]),
        'G': np.sum(mismatches_array[13:])
    }
    nucl_choices = {
        'A': (
            ['T', 'C', 'G'],
            [count / sums['A'] for count in mismatches_array[1:4]]
            ),
        'T': (
            ['A', 'C', 'G'],
            [count / sums['T'] for count in mismatches_array[5:8]]
            ),
        'C': (
            ['A', 'T', 'G'],
            [count / sums['C'] for count in mismatches_array[9:12]]
            ),
        'G': (
            ['A', 'T', 'C'],
            [count / sums['G'] for count in mismatches_array[13:]]
            )
    }
    return nucl_choices


def indel_rate(mismatches_array):
    """from the raw mismatches at one position, returns nucleotides
    and probabilties of indel"""
    sums = {
        'A': np.sum(mismatches_array[0:4]),
        'T': np.sum(mismatches_array[6:10]),
        'C': np.sum(mismatches_array[12:16]),
        'G': np.sum(mismatches_array[18:22])
    }
    indels = {
        'A': (
            ['1', '2'],
            [count / sums['A'] for count in mismatches_array[4:6]]
            ),
        'T': (
            ['1', '2'],
            [count / sums['T'] for count in mismatches_array[10:12]]
            ),
        'C': (
            ['1', '2'],
            [count / sums['C'] for count in mismatches_array[16:18]]
            ),
        'G': (
            ['1', '2'],
            [count / sums['G'] for count in mismatches_array[22:]]
            )
    }
    return indels


def quality_distribution(model, bam_file):
    """Generate numpy histograms for each position of the input mapped reads.
    A histogram contains the distribution of the phred scores for one position
    in all the reads. Returns a numpy array of the histograms for each position

    Arguments:
        bam_file (:obj:`str`): input bam file

    Returns:
        tuple: (histograms_forward, histograms_reverse)
    """
    # deal with the forward reads
    with pysam.AlignmentFile(bam_file, "rb") as bam:
        array_gen_f = (np.array(
            read.query_qualities) for read in bam.fetch()
                if not read.is_unmapped and read.is_read1)
        if model == 'cdf':
            histograms_forward = [np.histogram(
                i, bins=range(0, 41)) for i in zip(*array_gen_f)]
        elif model == 'kde':
            quals_forward = [i for i in zip(*array_gen_f)]

    # deal with the reverse reads
    with pysam.AlignmentFile(bam_file, "rb") as bam:
        array_gen_r = (np.array(
            read.query_qualities) for read in bam.fetch()
                if not read.is_unmapped and read.is_read2)
        if model == 'cdf':
            histograms_reverse = [np.histogram(
                i, bins=range(0, 41)) for i in zip(*array_gen_r)]
        elif model == 'kde':
            quals_reverse = [i for i in zip(*array_gen_r)]

    # calculate weights and indices
    if model == 'cdf':
        weights_forward = []
        weights_reverse = []
        for hist in histograms_forward:
            values, indices = hist
            weights = values / np.sum(values)
            weights_forward.append((indices, weights))
        for hist in histograms_reverse:
            values, indices = hist
            weights = values / np.sum(values)
            weights_reverse.append((indices, weights))
        return weights_forward, weights_reverse

    if model == 'kde':
        cdfs_forward = []
        cdfs_reverse = []
        for x in quals_forward:
            # print(x)
            kde = stats.gaussian_kde(x, bw_method=0.2 / np.std(x, ddof=1))
            kde = kde.evaluate(range(41))
            cdf = np.cumsum(kde)
            cdf = cdf / cdf[-1]
            cdfs_forward.append(cdf)
        for x in quals_reverse:
            kde = stats.gaussian_kde(x, bw_method=0.2 / np.std(x, ddof=1))
            kde = kde.evaluate(range(41))
            cdf = np.cumsum(kde)
            cdf = cdf / cdf[-1]
            cdfs_reverse.append(cdf)
        return cdfs_forward, cdfs_reverse


def get_insert_size(bam_file):
    """Get the mean insert size give mapped reads in a bam file

    Arguments:
        bam_file (:obj:`str`): input bam file

    Returns:
        int: mean insert size"""
    with pysam.AlignmentFile(bam_file, "rb") as bam:
        i_size_dist = [
            abs(read.template_length) for read in bam.fetch()
            if not read.is_unmapped and read.is_proper_pair]
        i_size = np.mean(i_size_dist)
    return int(i_size)


def write_to_file(read_length, hist_f, hist_r, sub_f, sub_r, indels_f,
                  indels_r, i_size, output):
    """write variables to a .npz file"""
    np.savez_compressed(
        output,
        read_length=read_length,
        insert_size=i_size,
        quality_hist_forward=hist_f,
        quality_hist_reverse=hist_r,
        subst_choices_forward=sub_f,
        subst_choices_reverse=sub_r,
        indels_forward=indels_f,
        indels_reverse=indels_r
    )
