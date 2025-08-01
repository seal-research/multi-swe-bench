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
        return "python:3.11-slim"
    
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
                """ls -al
###ACTION_DELIMITER###
pip install -e . && pip install -r requirements-dev.txt
###ACTION_DELIMITER###
cat > /home/moto/test_commands.sh <<'EOF'
pytest -sv -rs --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
pytest -sv -rs ./tests/test_xray
MOTO_CALL_RESET_API=false pytest -sv --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs --dist loadscope
EOF
chmod +x /home/moto/test_commands.sh
###ACTION_DELIMITER###
bash /home/moto/test_commands.sh"""
            ),
            File(
                ".",
                "run.sh",
                """#!/bin/bash
cd /home/{pr.repo}
pytest -sv -rs --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
pytest -sv -rs ./tests/test_xray
MOTO_CALL_RESET_API=false pytest -sv --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs --dist loadscope

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
pytest -sv -rs --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
pytest -sv -rs ./tests/test_xray
MOTO_CALL_RESET_API=false pytest -sv --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs --dist loadscope

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
pytest -sv -rs --cov=moto --cov-report xml ./tests/ --ignore tests/test_batch --ignore tests/test_ec2 --ignore tests/test_sqs
pytest -sv -rs ./tests/test_xray
MOTO_CALL_RESET_API=false pytest -sv --cov=moto --cov-report xml --cov-append -n 4 ./tests/test_batch ./tests/test_ec2 ./tests/test_sqs --dist loadscope

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
FROM python:3.11-slim

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
RUN git checkout 147049e97a54166a60bdc57de0dfe61227415779

RUN git checkout {pr.base.sha}"""
        dockerfile_content += f"""
{copy_commands}
"""
        return dockerfile_content.format(pr=self.pr)


@Instance.register("getmoto", "moto_5_0_21")
class MOTO_5_0_21(Instance):
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
        import re
        import json
        from collections import OrderedDict
        # Use regex to match test result lines and extract test names and statuses
        # Pattern: <test_path>::<test_name>[<params>] <STATUS> (optional reason)
        test_result_pattern = re.compile(r'^(\S.*?::\S.*?)\s+(PASSED|FAILED|SKIPPED)(?:\s*\(.*\))?$')
        test_status = OrderedDict()  # test_name -> last status
        for line in log.splitlines():
            line = line.strip()
            # Remove ANSI escape sequences
            line = re.sub(r'\x1b\[[0-9;]*m', '', line)
            match = test_result_pattern.match(line)
            if match:
                test_name, status = match.group(1), match.group(2)
                test_status[test_name] = status
        passed_tests = set()
        failed_tests = set()
        skipped_tests = set()
        for test_name, status in test_status.items():
            if status == "PASSED":
                passed_tests.add(test_name)
            elif status == "FAILED":
                failed_tests.add(test_name)
            elif status == "SKIPPED":
                skipped_tests.add(test_name)
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
