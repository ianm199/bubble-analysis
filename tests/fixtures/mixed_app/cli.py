import sys

from errors import ValidationError


def main():
    if len(sys.argv) < 2:
        raise ValueError("Missing argument")
    run_validation(sys.argv[1])


def run_validation(path):
    raise ValidationError(f"Invalid file: {path}")


if __name__ == "__main__":
    main()
