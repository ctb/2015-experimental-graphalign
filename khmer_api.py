from screed.screedRecord import _screed_record_dict
import os
from khmer.utils import write_record, write_record_pair
import khmer, sys, screed, khmer.utils
from khmer.utils import broken_paired_reader

def clean_reads(input_stream):
    for n, is_pair, read1, read2 in input_stream:
        read1.sequence = read1.sequence.upper()
        read1.sequence = read1.sequence.replace('N', 'A')

        if read2:
            read2.sequence = read2.sequence.upper()
            read2.sequence = read2.sequence.replace('N', 'A')

        yield n, is_pair, read1, read2


def output_reads(input_stream, out_fp):
    for n, is_pair, read1, read2 in input_stream:
        if is_pair:
            write_record_pair(read1, read2, out_fp)
        else:
            write_record(read1, out_fp)


def build_graph(input_stream, graph):
    for n, is_pair, read1, read2 in input_stream:
        graph.consume(read1.sequence)
        if is_pair:
            graph.consume(read2.sequence)


def diginorm(input_stream, ct, coverage):
    n = 0
    discard = 0
    for _, is_pair, read1, read2 in input_stream:
        if is_pair:
            med1, _, _ = ct.get_median_count(read1.sequence)
            med2, _, _ = ct.get_median_count(read2.sequence)

            if med1 < coverage or med2 < coverage:
                ct.consume(read1.sequence)
                ct.consume(read2.sequence)
                yield n, True, read1, read2
                n += 2
        else:
            med, _, _ = ct.get_median_count(read1.sequence)
            if med < coverage:
                ct.consume(read1.sequence)
                yield n, False, read1, None
                n += 1


def trim(input_stream, ct, normalize_coverage, trusted_coverage):
    n = 0
    for _, is_pair, read1, read2 in input_stream:
        if is_pair:
            med1, _, _ = ct.get_median_count(read1.sequence)
            med2, _, _ = ct.get_median_count(read2.sequence)

            if med1 >= normalize_coverage and med2 >= normalize_coverage:
                read1 = _trim_record(read1, ct, trusted_coverage)
                read2 = _trim_record(read2, ct, trusted_coverage)
            yield n, True, read1, read2
            n += 2
        else:
            med, _, _ = ct.get_median_count(read1.sequence)
            if med >= normalize_coverage:
                read1 = _trim_record(read1, ct, trusted_coverage)
            yield n, False, read1, None
            n += 1


def streamtrim(input_stream, ct, normalize_coverage, trusted_coverage):
    import khmer.utils
    vault = TemporaryReadStorage()
    
    n = 0
    for _, is_pair, read1, read2 in input_stream:
        if is_pair:
            med1, _, _ = ct.get_median_count(read1.sequence)
            med2, _, _ = ct.get_median_count(read2.sequence)

            if med1 < normalize_coverage or med2 < normalize_coverage:
                ct.consume(read1.sequence)
                ct.consume(read2.sequence)
                vault.save(read1)
                vault.save(read2)
            else:
                read1 = _trim_record(read1, ct, trusted_coverage)
                read2 = _trim_record(read2, ct, trusted_coverage)
                yield n, True, read1, read2
                n += 2
        else:
            med, _, _ = ct.get_median_count(read1.sequence)
            if med < normalize_coverage:
                ct.consume(read1.sequence)
                vault.save(read1)
            else:
                read1 = _trim_record(read1, ct, trusted_coverage)
                yield n, False, read1, None
                n += 1

    # now do 2nd pass across reads saved as being too low coverage.
    vault_reads = khmer.utils.broken_paired_reader(vault)
    for m, is_pair, read1, read2 in trim(vault_reads, ct,
                                         normalize_coverage, trusted_coverage):
        yield n + m, is_pair, read1, read2


####


class TemporaryReadStorage(object):
    def __init__(self):
        self.x = []
        
    def save(self, read):
        self.x.append(read)

    def __iter__(self):
        return self

    def next(self):
        try:
            return self.x.pop(0)
        except IndexError:
            raise StopIteration


def _trim_record(read, ct, cutoff):
    _, trim_at = ct.trim_on_abundance(read.sequence, cutoff)
    if trim_at < ct.ksize() or trim_at == len(read.sequence):
        return read
    
    new_read = _screed_record_dict()
    new_read.name = read.name
    new_read.sequence = read.sequence[:trim_at]
    if hasattr(read, 'quality'):
        new_read.quality = read.quality[:trim_at]

    return new_read


def broken_paired_to_single(input_stream):
    for _, is_pair, read1, read2 in input_stream:
        yield read1
        if is_pair:
            yield read2

###


def test_diginorm():
    filename = 'test_files/simple-metagenome-reads.fa'

    graph = khmer.new_counting_hash(20, 1e7, 4)
    out_fp = open(os.path.basename(filename) + '.keep', 'w')

    ## khmer scripts/normalize-by-median.py, using generators
    input_iter = screed.open(filename)
    input_iter = broken_paired_reader(input_iter)
    input_iter = clean_reads(input_iter)
    input_iter = diginorm(input_iter, graph, 20)

    script_result = screed.open('test_files/'
                                'simple-metagenome-reads.fa.keep.k20.C20')
    for read_a, read_b in zip(broken_paired_to_single(input_iter), script_result):
        print read_a.name
        assert read_a == read_b, (read_a, read_b)


if __name__ == '__main__':
    filename = sys.argv[1]

    graph = khmer.new_counting_hash(20, 1e7, 4)
    out_fp = open(os.path.basename(filename) + '.abundtrim', 'w')

    ## khmer scripts/trim-low-abund.py -V, using generators
    input_iter = screed.open(filename)
    input_iter = broken_paired_reader(input_iter)
    input_iter = clean_reads(input_iter)
    input_iter = streamtrim(input_iter, graph, 20, 2)
    output_reads(input_iter, out_fp)
    
    graph = khmer.new_counting_hash(20, 1e7, 4)
    out_fp = open(os.path.basename(filename) + '.keep', 'w')

    ## khmer scripts/normalize-by-median.py, using generators
    input_iter = screed.open(filename)
    input_iter = broken_paired_reader(input_iter)
    input_iter = clean_reads(input_iter)
    input_iter = diginorm(input_iter, graph, 20)
    output_reads(input_iter, out_fp)
