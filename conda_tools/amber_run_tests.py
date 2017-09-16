#!/usr/bin/env python
# Run most of AmberTools serial tests
''' Require: AMBERHOME

You need to call amber.setup_test_folders first (only do once)

     amber.setup_test_folders

Then run test (anywhere)

    amber.run_tests

Adjust the test by updating env TEST_TASK (please lookt at the code)
'''

from time import time
from contextlib import contextmanager
import os
import sys
import subprocess
import numpy as np
import multiprocessing
import functools
import itertools
import random
import json
import logging


logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


@contextmanager
def change_folder(where):
    here = os.getcwd()
    os.chdir(where)
    yield
    os.chdir(here)


def gather_dif_files(amberhome):
    logging.info("Writing diff files to test_dif.log")
    with open('test_dif.log', 'w') as fdif:
        with change_folder(amberhome):
            output = subprocess.check_output(
                'find . -iname "*.dif"', shell=True).decode()

            files = [fn for fn in output.split('\n') if fn]
            for fn in files:
                logging.info(fn)
                with open(fn) as fh:
                    fdif.write('FILENAME: {}\n'.format(fn))
                    fdif.write(fh.read())


def get_env_from_lines(env_name, lines):
    # type: (str, List[str]) -> str
    for line in lines:
        if line.startswith(env_name + '='):
            break
    return line.split('=')[-1].strip()


def get_bunch_of_individual_tests(test_name, makefile):
    first_layer = get_tests_from_test_name(test_name, makefile, False)
    if first_layer[0].startswith('cd'):
        return get_tests_from_test_name(test_name, makefile, True)
    second_layer = []
    for line in itertools.chain.from_iterable([
        get_tests_from_test_name(tn, makefile, True) for tn in first_layer]):
        if line:
            second_layer.append(line)
    return second_layer


def get_tests_from_test_name(test_name, makefile_fn, deeper=False):
    # type: (str, str, bool) -> List[str]
    # test.serial.sander.MM has a bunch of small tests.
    config_fn = os.path.join(os.getenv('AMBERHOME'), 'config.h')
    amber_source = get_env_from_lines('AMBER_SOURCE', open(config_fn).readlines())

    if hasattr(makefile_fn, 'readlines'):
        lines = makefile_fn.readlines()
    else:
        with open(makefile_fn) as fh:
            lines = fh.readlines()
    lines = [(line.replace('$(BINDIR)', '$AMBERHOME/bin')
                  .replace('$(MAKE)', 'make')
                  .replace('$(AMBER_SOURCE)', amber_source)
                  .replace('$(NETCDF)', '$AMBERHOME/include/netcdf.mod'))
            for line in lines]
    for index, line in enumerate(lines):
        if line.strip().startswith('-'):
            lines[index] = line.replace('-', '', 1)

    index_0 = 0
    index_next = -1
    for index, line in enumerate(lines):
        if line.startswith(test_name + ':'):
            break
    index_0 = index

    for index in range(index_0 + 1, 10000):
        try:
            if lines[index].startswith('test.'):
                break
        except IndexError:
            break

    index_next = index
    if deeper:
        return [line.strip().replace('make k', 'make -k')
                for line in lines[index_0+1:index_next] if not line.startswith('#') and line.strip()]
    else:
        my_lines = [
            word for word in ''.join(lines[index_0:index_next]).strip().split()
            if word != '\\'
        ]
        my_lines.pop(0)
        return my_lines


def remove_excluded_lines(excluded_lines, target):
    # type: (List[str], List[Tuple(str, str)]) -> None
    for line in excluded_lines:
        for line2 in target:
            if line in line2[0]:
                target.remove(line2)


def create_test_suite(excluded_tests):
    # type: (List[str]) -> Dict[str, List[str]]
    amberhome = os.getenv('AMBERHOME')
    if amberhome is None:
        raise EnvironmentError("Must set AMBERHOME")

    amber_test_dir = amberhome + '/test'
    ambertools_test_dir = amberhome + '/AmberTools/test'

    amber_test_suite_dict = {
        'serial.MM': [
            test
            for test in get_tests_from_test_name(
                'test.serial.sander.MM', amber_test_dir + '/Makefile') + [
                    'test.nmode',
                ] if test not in ['test.serial.sander.emap']
        ],
        'serial.QMMM':
        get_tests_from_test_name('test.serial.QMMM',
                                 amber_test_dir + '/Makefile'),
        'serial.sander.SEBOMD': ['test.serial.sander.SEBOMD'],
        'sanderapi': ['test.serial.sanderapi'],
    }

    ambertools_test_suite_dict = {
        'fast': [
            'test.cpptraj', 'test.pytraj', 'test.parmed', 'test.pdb4amber',
            'test.leap', 'test.antechamber', 'test.unitcell', 'test.reduce',
            'test.nab', 'test.mdgx', 'test.resp', 'test.sqm', 'test.gbnsr6',
            'test.elsize', 'test.paramfit', 'test.FEW', 'test.cphstats',
            'test.cpinutil'
        ],
        'mmpbsa': [
            'test.mmpbsa',
            'test.mm_pbsa',
        ],
        'pbsa': [
            'test.pbsa',
        ],
        'rism': ['test.rism1d', 'test.rism3d.periodic'],
        'python': [
            'test.pytraj', 'test.parmed',
            'test.pdb4amber',
            'test.pymsmt'
        ],
    }

    for test_suite_dict in [amber_test_suite_dict, ambertools_test_suite_dict]:
        for k in test_suite_dict:
            for test in excluded_tests:
                try:
                    test_suite_dict[k].remove(test)
                except ValueError:
                    pass


    def gather(suite_dict, test_dir):
        for task, suite in suite_dict.items():
            suite_dict[task] = [(test_name, test_dir) for test_name in suite]

    gather(ambertools_test_suite_dict, ambertools_test_dir)
    gather(amber_test_suite_dict, amber_test_dir)

    all_suits = amber_test_suite_dict.copy()
    all_suits.update(ambertools_test_suite_dict)

    return all_suits


def failed(output):
    return ('Program error' in output or
            'possible FAILURE' in output or
            'No rule to make target' in output or
            'command not found' in output or
            'FAILED' in output)


def program_error(output):
    return ('Program error' in output or
            'No rule to make target' in output or
            'command not found' in output)


def execute(cmds):
    then = time()
    # adapted from StackOverflow
    # http://stackoverflow.com/a/4418193
    command = ' '.join(cmds)
    print(command)
    output_lines = []
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        shell=True)

    # Poll process for new output until finished
    while True:
        nextline = process.stdout.readline().decode('utf-8')
        if nextline == '' and process.poll() is not None:
            break
        sys.stdout.write('.')
        sys.stdout.flush()
        output_lines.append(nextline)
    output = ''.join(output_lines)
    now = time()
    time_diff = now - then
    if failed(output):
        print('{0:.1f} (s), FAILURE'.format(time_diff))
    else:
        print('{0:.1f} (s), PASSED'.format(time_diff))
    return output, time_diff


def run_circleci(test_suite):
    node_index = int(os.getenv('CIRCLE_NODE_INDEX'))
    node_total = int(os.getenv('CIRCLE_NODE_TOTAL'))
    logging.info("Running on circleci containers")
    logging.info('node_index = ', node_index)
    logging.info('node_total= ', node_total)

    if node_index is None:
        raise ValueError("Must have CIRCLE_NODE_INDEX and CIRCLE_NODE_TOTAL env")
    test_suite_chunks = np.array_split(sorted(set(test_suite)), node_total)
    return run_chunk(0, [test_suite_chunks[node_index],])


def run_chunk(rank, test_suite_chunks, add_make=True):
    # type: (List[[str, str]]) -> None
    TIME_DICT = dict()
    ALL_OUTPUTS = []
    ERRORS = []
    test_suite = test_suite_chunks[rank]
    logging.debug('rank={}, test_suite={}'.format(rank, test_suite))
    for (test_name, test_dir) in test_suite:
        if add_make:
            cmds = ['cd', test_dir, '&&', 'make', test_name]
        else:
            cmds = ['cd', test_dir, '&&', test_name]
        output, time_diff = execute(cmds)
        TIME_DICT[test_name] = time_diff
        lines = output.split('\n')
        ALL_OUTPUTS.extend(lines)
        for index, line in enumerate(lines):
            if failed(line):
                ERRORS.append('==> ' + " ".join(cmds))
                ERRORS.append(" ".join(lines[index-1:index+1]))
    return TIME_DICT, ALL_OUTPUTS, ERRORS


def run_all(test_suite, num_cpus, add_make=False):
    if num_cpus == 1:
        logging.info("Run test in serial")
        return run_chunk(0, [test_suite], add_make)
    else:
        logging.info("Run test in parallel")
        if num_cpus < 1:
            num_cpus = multiprocessing.cpu_count()
        num_cpus = min(len(test_suite), num_cpus)
        print('num_cpus', num_cpus)
        random.shuffle(test_suite)
        test_suite_chunks = np.array_split(list(set(test_suite)), num_cpus)
        pool = multiprocessing.Pool(num_cpus)
        func =  functools.partial(run_chunk, test_suite_chunks=test_suite_chunks,
                add_make=add_make) 
        outputs = pool.map(func, range(num_cpus))
        pool.close()

        TIME_DICT = outputs[0][0]
        for t in outputs[1:]:
            TIME_DICT.update(t[0])

        ALL_OUTPUTS = outputs[0][1]
        for a in outputs[1:]:
            ALL_OUTPUTS.extend(a[1])

        ERRORS = outputs[0][2]
        for e in outputs[1:]:
            ERRORS.extend(e[2])
        return TIME_DICT, ALL_OUTPUTS, ERRORS


def timer(msg=''):
    def wrap_0(func):
        def wrap(*args, **kwargs):
            t0 = time()
            out = func(*args, **kwargs)
            long_msg = "Finished {} in {:04.2f} (minutes)".format(msg,
                    (time() - t0) / 60.)
            print(long_msg)
            with open('test_summary.log', 'a') as fh:
                fh.write(long_msg + '\n')
            return out
        return wrap
    return wrap_0


@timer(msg='testing AmberTools')
def test_me(opt):
    sanderapi_tests = [
        'test.parm7', 'Fortran', 'Fortran2', 'C', 'CPP', 'Python', 'clean'
    ]
    amberhome = os.getenv('AMBERHOME')
    if not amberhome:
        raise EnvironmentError("Must set AMBERHOME")
    ambertools_test_dir = amberhome + '/AmberTools/test'
    amber_test_dir = amberhome + '/test'

    ERRORS = []
    ALL_OUTPUTS = []
    TIME_DICT = {}
    test_suite_dict = create_test_suite(opt.exclude and opt.exclude.get('test_name') or [])
    test_task = opt.task

    try:
        if opt.task in ['serial.MM.0', 'serial.MM.1']:
            test_task_update = 'serial.MM'
        elif opt.task in ['serial.QMMM.0', 'serial.QMMM.1']:
            test_task_update = 'serial.QMMM'
        else:
            test_task_update = test_task
        test_suite = test_suite_dict[
            test_task_update] if test_task_update != 'all' else sum(test_suite_dict.values(), [])
        if test_task_update == 'python':
            test_suite.extend(test_suite_dict['sanderapi'])
    except KeyError:
        test_dir = amber_test_dir if opt.use_amber_test_dir else ambertools_test_dir
        test_suite = [
            (test_task, test_dir),
        ]

    if not opt.make:
        suite = []
        for test_task, test_dir in test_suite:
            if 'AmberTools' in test_dir:
                makefile = os.path.join(ambertools_test_dir, 'Makefile')
            else:
                makefile = os.path.join(amber_test_dir, 'Makefile')
            suite.extend([(tn, test_dir) for tn in
                get_bunch_of_individual_tests(test_task, makefile)])
        test_suite = suite[:]
        if opt.task in {'serial.MM.0', 'serial.MM.1', 'serial.QMMM.0',
                'serial.QMMM.1'}:
            index = int(opt.task.split('.')[-1])
            test_suite = np.array_split(test_suite, 2)[index].tolist()
            test_suite = [tuple(t) for t in test_suite]

    remove_excluded_lines(opt.exclude and opt.exclude.get('test_line') or [], test_suite)
    print('test_suite')
    print('Number of tests = %s' % len(test_suite))
    for tn in sorted(test_suite):
        logging.debug(tn)

    if opt.collect_only:
        return []

    # amberXX/test/
    if test_task in ['serial.MM', 'serial.QMMM', 'serial.sander.SEBOMD']:
        logging.info('serial MM and QMMM')
        test_folder = amber_test_dir
    # amberXX/AmberTools/test/
    else:
        logging.info(amberhome + '/AmberTools/test/')
        test_folder = ambertools_test_dir

    if opt.circleci:
        TIME_DICT, ALL_OUTPUTS, ERRORS = run_circleci(test_suite)
    else:
        TIME_DICT, ALL_OUTPUTS, ERRORS = run_all(test_suite, opt.num_cpus, opt.make)

    if ERRORS:
        for out in ERRORS:
            print(out)

    n_passes = n_fails = n_program_errors = 0

    with open('test_out.log', 'w') as fh:
        for line in ALL_OUTPUTS:
            try:
                fh.write(line + '\n')
            except UnicodeError:
                # UnicodeEncodeError: 'ascii' codec can't encode character u'\u2018' in position 18: ordinal not in range(128)
                # FIXME: why?
                pass
            if 'PASSED' in line:
                n_passes += 1
            if program_error(line):
                n_program_errors += 1
            if ('possible FAILURE' in line or
                'FAILED' in line):
                n_fails += 1

    gather_dif_files(amberhome)

    print(TIME_DICT)
    with open('test_timing.log', 'w') as fh:
        for k, v in sorted(TIME_DICT.items(), key=lambda x: x[1],
                          reverse=True):
            fh.write("{:32}: {:06.2f} (s)\n".format(k, v))

    with open('test_summary.log', 'w') as fh:
        summary = """
{} file comparisons passed
{} file comparisons failed
{} tests experienced errors
""".format(n_passes, n_fails, n_program_errors)
        fh.write(summary)
        print(summary)

    return ERRORS


def main(args=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--task',
            default='fast',
            help='test task')
    parser.add_argument('-x', '--exclude',
            default=None,
            help='Exlude tests')
    parser.add_argument('-n', '--num-cpus',
            default=-1,
            type=int,
            help='Run test in serial')
    parser.add_argument('-d', '--use-amber-test-dir',
            action='store_true',
            help='Explicitly run test in $AMBERHOME/test folder')
    parser.add_argument('-c', '--circleci',
            action='store_true',
            help='If True, run test in parallel using circleci containers')
    parser.add_argument('--make',
            action='store_true',
            help='If True, run test in parallel using circleci containers')
    parser.add_argument('--collect-only',
            action='store_true',
            help='If True, only collect test suite and logging.info to stdout')
    parser.add_argument('--debug',
            action='store_true',
            help='If True, debug')
    opt = parser.parse_args(args)
    if opt.debug:
        logger.setLevel(logging.DEBUG)

    if opt.exclude:
        # "test.parmed, test.pytraj"
        with open(opt.exclude) as fh:
            opt.exclude = json.loads(fh.read())
        print('TEST EXCLUDED', opt.exclude)
    errors = test_me(opt)
    assert len(errors) == 0


if __name__ == '__main__':
    main()
