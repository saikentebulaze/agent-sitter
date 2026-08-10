from __future__ import annotations

import argparse
from pathlib import Path

from common import fail
from governed_validation import validate_investigation_policy
from work_graph import WorkGraphError, load_yaml


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        validate_investigation_policy(load_yaml(args.path))
    except WorkGraphError as error:
        fail(str(error))
    print("investigation_state: valid")


if __name__ == "__main__":
    main()
