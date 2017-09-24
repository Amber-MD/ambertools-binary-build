"""Change hard-coded shebang to "#!/usr/bin/env python"

Example:
    python update_shebang.py $AMBERHOME
"""
import argparse


def update_python_env(bin_dir):
    files = [fn for fn in glob(bin_dir + '/*') if os.path.isfile(fn)]
    for fn in files:
        try:
            content = ''
            with open(fn) as fh:
                line = fh.readline().strip()
                if 'bin/python' in line:
                    fh.seek(0)
                    content = fh.read().replace(line, '#!/usr/bin/env python')
            # overwrite
            if content:
                with open(fn, 'w') as fh:
                    fh.write(content)
                subprocess.check_call(['chmod', '+x', fn])
        except UnicodeError:
            pass


def main(args=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("prefix")
    opt = parser.parse_args(args)
    update_python_env(os.path.join(prefix, 'bin'))


if __name__ == '__main__':
    main()
