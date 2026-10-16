"""Separate entrypoint using the existing owned-process transport."""
from wind_worker import main
from security_wind import perform

if __name__ == "__main__":
    main(perform)
