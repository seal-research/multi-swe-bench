import re
import json
from typing import Optional, Union

from multi_swe_bench.harness.image import Config, File, Image
from multi_swe_bench.harness.instance import Instance, TestResult
from multi_swe_bench.harness.pull_request import PullRequest


class ImageDefault(Image):
    def __init__(self, pr: PullRequest, config: Config):
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    @property
    def config(self) -> Config:
        return self._config

    def dependency(self) -> str:
        return "python:3.7-slim"
    
    def image_prefix(self) -> str:
        return "envagent"
       
    def image_tag(self) -> str:
        return f"pr-{self.pr.number}"

    def workdir(self) -> str:
        return f"pr-{self.pr.number}"

    def files(self) -> list[File]:
        return [
            File(
                ".",
                "fix.patch",
                f"{self.pr.fix_patch}",
            ),
            File(
                ".",
                "test.patch",
                f"{self.pr.test_patch}",
            ),
            File(
                ".",
                "prepare.sh",
                """ls -la
###ACTION_DELIMITER###
python setup.py develop
###ACTION_DELIMITER###
pip install --upgrade pip setuptools
###ACTION_DELIMITER###
python setup.py develop
###ACTION_DELIMITER###
python --version
###ACTION_DELIMITER###
apt-get update && apt-get install -y python3.9 python3.9-venv python3.9-dev
###ACTION_DELIMITER###
pip install 'markupsafe==2.0.1'
###ACTION_DELIMITER###
python setup.py develop
###ACTION_DELIMITER###
pip install 'pyyaml==5.4.1'
###ACTION_DELIMITER###
pip install -r requirements-dev.txt
###ACTION_DELIMITER###
pip install 'zipp<3.8.0'
###ACTION_DELIMITER###
pip uninstall -y typing_extensions && pip install 'typing_extensions<4.0.0'
###ACTION_DELIMITER###
rm -rf /usr/local/lib/python3.7/site-packages/typing_extensions*
###ACTION_DELIMITER###
pip install 'typing_extensions<4.0.0'
###ACTION_DELIMITER###

###ACTION_DELIMITER###
pip install -r requirements-dev.txt
###ACTION_DELIMITER###
rm -rf /usr/local/lib/python3.7/site-packages/zipp* && pip install 'zipp<3.8.0'
###ACTION_DELIMITER###
pip install -r requirements-dev.txt
###ACTION_DELIMITER###
echo "pytest -sv --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
MOTO_CALL_RESET_API=false pytest --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs" > test_commands.sh && chmod +x test_commands.sh"""
            ),
            File(
                ".",
                "run.sh",
                """#!/bin/bash
cd /home/{pr.repo}
pytest -sv --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
MOTO_CALL_RESET_API=false pytest --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs

""".format(
                    pr=self.pr
                ),
            ),
            File(
                ".",
                "test-run.sh",
                """#!/bin/bash
cd /home/{pr.repo}
if ! git -C /home/{pr.repo} apply --whitespace=nowarn /home/test.patch; then
    echo "Error: git apply failed" >&2
    exit 1  
fi
pytest -sv --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
MOTO_CALL_RESET_API=false pytest --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs

""".format(
                    pr=self.pr
                ),
            ),
            File(
                ".",
                "fix-run.sh",
                """#!/bin/bash
cd /home/{pr.repo}
if ! git -C /home/{pr.repo} apply --whitespace=nowarn  /home/test.patch /home/fix.patch; then
    echo "Error: git apply failed" >&2
    exit 1  
fi
pytest -sv --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
MOTO_CALL_RESET_API=false pytest --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs

""".format(
                    pr=self.pr
                ),
            ),
        ]

    def dockerfile(self) -> str:
        copy_commands = ""
        for file in self.files():
            copy_commands += f"COPY {file.name} /home/\n"

        dockerfile_content = """
# This is a template for creating a Dockerfile to test patches
# LLM should fill in the appropriate values based on the context

# Choose an appropriate base image based on the project's requirements - replace [base image] with actual base image
# For example: FROM ubuntu:**, FROM python:**, FROM node:**, FROM centos:**, etc.
FROM python:3.7-slim

## Set noninteractive
ENV DEBIAN_FRONTEND=noninteractive

# Install basic requirements
# For example: RUN apt-get update && apt-get install -y git
# For example: RUN yum install -y git
# For example: RUN apk add --no-cache git
RUN apt-get update && apt-get install -y git

# Ensure bash is available
RUN if [ ! -f /bin/bash ]; then         if command -v apk >/dev/null 2>&1; then             apk add --no-cache bash;         elif command -v apt-get >/dev/null 2>&1; then             apt-get update && apt-get install -y bash;         elif command -v yum >/dev/null 2>&1; then             yum install -y bash;         else             exit 1;         fi     fi

WORKDIR /home/
COPY fix.patch /home/
COPY test.patch /home/
RUN git clone https://github.com/getmoto/moto.git /home/moto

WORKDIR /home/moto
RUN git reset --hard
RUN git checkout 82ee649242037ab4945ad849cb48dec8f4ee2f80

RUN git checkout {pr.base.sha}"""
        dockerfile_content += f"""
{copy_commands}
"""
        return dockerfile_content.format(pr=self.pr)


@Instance.register("getmoto", "moto_4_0_6")
class MOTO_4_0_6(Instance):
    def __init__(self, pr: PullRequest, config: Config, *args, **kwargs):
        super().__init__()
        self._pr = pr
        self._config = config

    @property
    def pr(self) -> PullRequest:
        return self._pr

    def dependency(self) -> Optional[Image]:
        return ImageDefault(self.pr, self._config)

    def run(self, run_cmd: str = "") -> str:
        if run_cmd:
            return run_cmd

        return 'bash /home/run.sh'

    def test_patch_run(self, test_patch_run_cmd: str = "") -> str:
        if test_patch_run_cmd:
            return test_patch_run_cmd

        return "bash /home/test-run.sh"

    def fix_patch_run(self, fix_patch_run_cmd: str = "") -> str:
        if fix_patch_run_cmd:
            return fix_patch_run_cmd

        return "bash /home/fix-run.sh"


    def parse_log(self, log: str) -> TestResult:

        # Parse the log content and extract test execution results.
        passed_tests = set()
        failed_tests = set()
        skipped_tests = set()
        import re
        import json
        # Implement the log parsing logic here
        # Regex patterns for test results
        # Example: tests/test_file.py::test_name PASSED
        test_result_pattern = re.compile(r'^(?P<name>\S+::\S+) (?P<status>PASSED|FAILED|SKIPPED)')
        # Example: FAILED tests/test_file.py::test_name - <error message>
        failed_prefix_pattern = re.compile(r'^FAILED (?P<name>\S+::\S+)')
        for line in log.splitlines():
            m = test_result_pattern.match(line)
            if m:
                name = m.group('name')
                status = m.group('status')
                if status == 'PASSED':
                    passed_tests.add(name)
                elif status == 'FAILED':
                    failed_tests.add(name)
                elif status == 'SKIPPED':
                    skipped_tests.add(name)
                continue
            m2 = failed_prefix_pattern.match(line)
            if m2:
                name = m2.group('name')
                failed_tests.add(name)
        parsed_results = {
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "skipped_tests": skipped_tests
        }

        return TestResult(
            passed_count=len(passed_tests),
            failed_count=len(failed_tests),
            skipped_count=len(skipped_tests),
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            skipped_tests=skipped_tests,
        )
