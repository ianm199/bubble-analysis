import sys


def main():
    if len(sys.argv) < 2:
        raise ValueError("Missing argument")
    process_data(sys.argv[1])


def process_data(path):
    raise FileNotFoundError(f"File not found: {path}")


if __name__ == "__main__":
    main()
