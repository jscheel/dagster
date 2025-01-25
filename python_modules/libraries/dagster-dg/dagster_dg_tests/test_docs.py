import dataclasses
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from dagster._utils.env import environ

COMPONENTS_INTRO_DOCS = (
    Path(__file__).parent.parent.parent.parent.parent
    / "docs"
    / "docs-beta"
    / "docs"
    / "guides"
    / "build"
    / "components"
    / "index.md"
)

TEST_BLOCK_REGEX = (
    r"```((?:bash test(?: before=[^\n]+)?)|(?:toml|python|yaml) (?:cat|create)=[^\n]*)\n(.*?)\n```"
)


@dataclasses.dataclass
class CommandToRun:
    command: str
    expected_output: Optional[str]
    pre_command_to_run: Optional[str] = None


def test_docs_commands():
    assert COMPONENTS_INTRO_DOCS.exists()

    intro_docs_text = COMPONENTS_INTRO_DOCS.read_text()

    matches = re.findall(TEST_BLOCK_REGEX, intro_docs_text, re.MULTILINE | re.DOTALL)

    commands_with_output: list[CommandToRun] = []

    for match in matches:
        header, contents = match

        if header.startswith("bash test"):
            expected_output = None
            command = contents
            if "\n\n" in contents:
                command, expected_output = contents.split("\n\n", 1)
            command = command.strip().lstrip("$").strip()

            before = None
            if "nooutput" in header:
                expected_output = None
            if "before=" in header:
                before = header.split("before=")[1].strip()
            commands_with_output.append(
                CommandToRun(
                    command=command, expected_output=expected_output, pre_command_to_run=before
                )
            )

        elif "cat=" in header:
            filepath = header.split("cat=")[1].strip()
            assert re.match(r"[a-zA-Z0-9_\-\.]+", filepath)
            command = f"cat {filepath}"
            expected_output = "\n".join(
                line for line in contents.split("\n") if not line.strip().startswith("#")
            ).strip()
            commands_with_output.append(
                CommandToRun(command=command, expected_output=expected_output)
            )
        elif "create=" in header:
            filepath = header.split("create=")[1].strip()
            assert re.match(r"[a-zA-Z0-9_\-\.]+", filepath)
            command = f"rm {filepath}; echo '{contents}' > {filepath}"
            commands_with_output.append(CommandToRun(command=command, expected_output=None))

        else:
            raise ValueError(f"Unexpected header: {header}")

    with TemporaryDirectory() as tempdir, environ({"COLUMNS": "80"}):
        os.chdir(tempdir)
        subprocess.check_call(["uv", "pip", "install", "dg"])

        for cmd in commands_with_output:
            try:
                if cmd.pre_command_to_run:
                    subprocess.check_call(cmd.pre_command_to_run, shell=True)
                actual_output = (
                    subprocess.check_output(
                        f'{cmd.command}; echo "PWD=$(pwd)"', shell=True, stderr=subprocess.STDOUT
                    )
                    .decode("utf-8")
                    .strip()
                )
                actual_output, pwd = actual_output.split("PWD=")
                os.chdir(pwd)
            except subprocess.CalledProcessError as e:
                print(e.output)
                raise
            if cmd.expected_output:
                expected_output_regex = re.escape(cmd.expected_output).replace(r"\.\.\.", ".*")
                if not re.match(expected_output_regex, actual_output, re.MULTILINE | re.DOTALL):
                    print(f"Mismatch running command: {cmd.command}")
                    print("\nActual output:")
                    print(actual_output)
                    print("\n\nExpected output:")
                    print(str(expected_output_regex))
                else:
                    print(f"Command {cmd.command} passed")

                assert re.match(expected_output_regex, actual_output, re.MULTILINE | re.DOTALL)
