#!/usr/bin/python3

import click
import os
import glob
import tarfile
import gzip
import sys

@click.command()
@click.option("--dir", required=True, help="Path to directory containing ..._gitlab_backup.tar")
def main(dir):
    exit_code = 0

    # Find the last modified ..._gitlab_backup.tar file in the specified directory
    backup_files = glob.glob(os.path.join(dir, "*_gitlab_backup.tar"))

    if not backup_files:
        print("ERROR: No backup tar files found.")
        exit_code = 1

    else:
        latest_backup = max(backup_files, key=os.path.getmtime)
        print(f"SUCCESS: Found latest backup file: {latest_backup}.")

        with tarfile.open(latest_backup, "r") as tar:
            # Check that inside that tar file there is a db/database.sql.gz file
            try:
                db_member = tar.getmember("db/database.sql.gz")
                print(f"SUCCESS: Found database.sql.gz in {latest_backup}.")

                # Check database.sql.gz is bigger than 1 MB
                if db_member.size > 1 * 1024 * 1024:
                    print(f"SUCCESS: database.sql.gz size is {db_member.size} bytes, which is larger than 1 MB.")

                    db_file = tar.extractfile(db_member)
                    with gzip.open(db_file, 'rt') as f:
                        # Check that database.sql.gz starts with first 3 lines:
                        # --
                        # -- PostgreSQL database dump
                        # --
                        first_three_lines = [next(f).strip() for _ in range(3)]
                        expected_lines = [
                            "--",
                            "-- PostgreSQL database dump",
                            "--"
                        ]
                        if first_three_lines == expected_lines:
                            print("SUCCESS: database.sql.gz has the expected header lines.")
                            print("Found lines:")
                            for line in first_three_lines:
                                print(line)
                        else:
                            print("ERROR: database.sql.gz does not have the expected header lines.")
                            print("Found lines:")
                            for line in first_three_lines:
                                print(line)
                            exit_code = 1

                        # Check that database.sql.gz ends with such lines:
                        # --
                        # -- PostgreSQL database dump complete
                        # --
                        # <newline>
                        # \unrestrict <random text>
                        # <newline>
                        f.seek(0, os.SEEK_END)
                        f_size = f.tell()
                        buffer_size = 1024
                        if f_size < buffer_size:
                            buffer_size = f_size
                        f.seek(f_size - buffer_size)
                        lines = f.readlines()
                        last_six_lines = [line.strip() for line in lines[-6:]]
                        expected_end_lines = [
                            "--",
                            "-- PostgreSQL database dump complete",
                            "--",
                            "",
                            r"\unrestrict ",
                            ""
                        ]
                        if (last_six_lines[0] == expected_end_lines[0] and
                            last_six_lines[1] == expected_end_lines[1] and
                            last_six_lines[2] == expected_end_lines[2] and
                            last_six_lines[3] == expected_end_lines[3] and
                            last_six_lines[4].startswith(expected_end_lines[4]) and
                            last_six_lines[5] == expected_end_lines[5]):
                            print("SUCCESS: database.sql.gz has the expected footer lines.")
                            print("Found lines:")
                            for line in last_six_lines:
                                print(line)
                        else:
                            print("ERROR: database.sql.gz does not have the expected footer lines.")
                            print("Found lines:")
                            for line in last_six_lines:
                                print(line)
                            exit_code = 1

                else:
                    print(f"ERROR: database.sql.gz size is {db_member.size} bytes, which is not larger than 1 MB.")
                    exit_code = 1

            except KeyError:
                print(f"ERROR: database.sql.gz not found in {latest_backup}.")
                exit_code = 1

            # Check that inside that tar file there is a backup_information.yml file
            try:
                info_member = tar.getmember("backup_information.yml")
                print(f"SUCCESS: Found backup_information.yml in {latest_backup}.")

                # Check backup_information.yml contains a line starting with ':gitlab_version: '
                info_file = tar.extractfile(info_member)
                info_content = info_file.read().decode('utf-8')
                if any(line.startswith(":gitlab_version: ") for line in info_content.splitlines()):
                    print("SUCCESS: backup_information.yml contains :gitlab_version: entry.")
                else:
                    print("ERROR: backup_information.yml does not contain :gitlab_version: entry.")
                    exit_code = 1

            except KeyError:
                print(f"ERROR: backup_information.yml not found in {latest_backup}.")
                exit_code = 1

    # If all checks passed
    if exit_code != 0:
        print("ERROR: Some checks failed.")
        sys.exit(exit_code)
    else:
        print(f"SUCCESS: All checks passed for database.sql.gz in {latest_backup}.")
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
