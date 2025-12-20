import argparse

def check_port(value):
    port = int(value)
    if port < 1 or port > 65535:
        raise argparse.ArgumentTypeError(f"Port must be between 1 and 65535, got {value}")
    return port