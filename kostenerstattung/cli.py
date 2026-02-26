import argparse
import sys
import os
import logging

logger = logging.getLogger(__name__)
FORMAT = "[%(asctime)s %(levelname)5s] %(message)s"
handlers = [logging.StreamHandler()]
if "LOG_FILE" in os.environ:
    handlers.append(logging.FileHandler(os.environ["LOG_FILE"]))
logging.basicConfig(format=FORMAT, handlers=handlers, level=logging.INFO)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-backend", action="store_true", help="run backend")
    parser.add_argument("-g", "--generate-password", action="store_true", help="generate a password and hash you can put into the config file")
    parser.add_argument("-s", "--show-webling-configuration", action="store_true", help="show webling data (Buchungsperioden, Buchungskonten, etc. In the config file, you can specify the default Buchungsperiode and default Buchungskonto (Bankkonto))")
    parser.add_argument("--version", action="store_true", help="show version")

    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    if args.run_backend:
        from kostenerstattung.app import serve_backend
        serve_backend()
    elif args.generate_password:
        from kostenerstattung.utils import generate_password_hash
        generate_password_hash()
    elif args.show_webling_configuration:
        from kostenerstattung.webling import print_webling_data
        print_webling_data()
    elif args.version:
        from kostenerstattung.utils import get_version
        print(f"{sys.argv[0]} {get_version()}")


if __name__ == '__main__':
    main()
