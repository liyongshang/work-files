"""Execute the walkthrough in its own project directory and retain outputs."""
import argparse
from pathlib import Path

import nbformat
from nbclient import NotebookClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('notebook', type=Path)
    args = parser.parse_args()
    path = args.notebook.resolve()
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    NotebookClient(notebook, timeout=180, kernel_name='python3',
                   resources={'metadata': {'path': str(path.parent)}}).execute()
    nbformat.write(notebook, path)
    codes = [cell for cell in notebook.cells if cell.cell_type == 'code']
    assert all(cell.execution_count is not None for cell in codes)
    assert not any(output.output_type == 'error' for cell in codes for output in cell.outputs)
    print(f'Executed {len(codes)} code cells successfully: {path}')


if __name__ == '__main__':
    main()
