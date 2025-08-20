import logging
from pathlib import Path
from typing import Optional, Union
import subprocess, shutil, os

APPTAINER_BASH = "apptainer" if shutil.which("apptainer") else "singularity"

def check_files_exist(sandbox_path: Path, apptainer_base_file: Path, logger: logging.Logger):
    if sandbox_path.exists():
        shutil.rmtree(sandbox_path, ignore_errors=True)
        logger.info(f"Removed existing sandbox directory: {sandbox_path}")
    if apptainer_base_file.exists():
        os.remove(apptainer_base_file)
        logger.info(f"Removed existing Apptainer base image file: {apptainer_base_file}")

def pull_build(
    image_dir: Path, sif_name: str, image_full_name: str, files: list, logger: logging.Logger, g2: bool = False
):
    try:
        # Remove existing sandbox and base image if they exist
        sandbox_path = image_dir / "apptainer_sandbox"
        apptainer_base_file = image_dir / sif_name
        check_files_exist(sandbox_path, apptainer_base_file, logger)

        image_dir = str(image_dir)
        logger.info(
            f"Start building image `{image_full_name}`, working directory is `{image_dir}`"
        )

        # Pull the Apptainer base image
        logger.info("Pulling Apptainer image...")
        result = subprocess.run(
            [APPTAINER_BASH, "pull", sif_name, f"docker://{image_full_name}"],
            cwd=image_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            logger.info(f"Failed to pull Apptainer image:\n{result.stderr}")
            raise RuntimeError(f"Apptainer pull failed: {result.stderr}")

        # Build the Apptainer base sandbox
        logger.info("Building Apptainer sandbox...")
        result = subprocess.run(
            [APPTAINER_BASH, "build", "--sandbox", "apptainer_sandbox", sif_name],
            cwd=image_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            logger.info(f"Failed to build Apptainer sandbox image:\n{result.stderr}")
            raise RuntimeError(f"Apptainer build failed: {result.stderr}")
        
        if g2:
            # mkdir /scratch for sandbox to bind /scratch in container
            logger.info(f"mkdir {image_dir} in Apptainer sandbox...")
            result = subprocess.run(
                [APPTAINER_BASH, "exec", "--writable", "apptainer_sandbox", "bash", "-c", f"mkdir -p {image_dir}"],
                cwd=image_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode != 0:
                logger.info(f"Failed to mkdir {image_dir} in Apptainer sandbox:\n{result.stderr}")
                raise RuntimeError(f"Apptainer mkdir failed: {result.stderr}")
        
        # Copy files into the sandbox
        logger.info("Copying files into the sandbox...")
        for file_path in files:
            shutil.copy(file_path, f"{image_dir}/apptainer_sandbox/home/")

        # global env and proxy_setup
        
        # run prepare script
        logger.info("Running prepare script...")
        result = subprocess.run(
            [APPTAINER_BASH, "exec", "--writable", "apptainer_sandbox", "bash", "-c", 
                 f"cd apptainer_sandbox && bash home/prepare.sh"],
            cwd=image_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            logger.info(f"Failed to run prepare.sh in Apptainer sandbox:\n{result.stderr}")
            raise RuntimeError(f"Apptainer build failed: {result.stderr}")
        
    except Exception as e:
        logger.error(f"Unknown build error occurred: {e}")
        raise e

def run(
    image_dir: Path,
    run_command: str,
    output_path: Optional[Path] = None,
    logger: logging.Logger = None, 
) -> str:
    try:
        result = subprocess.run(
            [APPTAINER_BASH, "exec", "--writable", "apptainer_sandbox", "bash", "-c", 
                f"cd apptainer_sandbox && {run_command}"],
            cwd=str(image_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=None
        )
    
        output = result.stdout
        warning_line = []
        if output_path:
            with open(output_path, "w") as f:
                for line in output.splitlines():
                    if "WARNING: " in line:
                        warning_line.append(line)
                    else:
                        f.write(line + "\n")
                for line in warning_line:
                    f.write(line + "\n")
                if result.returncode != 0:
                    f.write(f"\n\nProcess returned non-zero exit code: {result.returncode}")
        
        return output

    except Exception as e:
        raise RuntimeError(f"An unexpected error occurred while running the command: {e}")
    
    finally:
        # Cleaning sandbox
        # Remove the Apptainer sandbox directory
        apptainer_base_file = image_dir / "apptainer_base.sif"
        sandbox_path = image_dir / "apptainer_sandbox"
        try:
            if apptainer_base_file.exists():
                os.remove(apptainer_base_file)
                logger.info(f"Removed Apptainer base image file: {apptainer_base_file}")
            if sandbox_path.exists():
                shutil.rmtree(sandbox_path, ignore_errors=True)
                logger.info(f"Removed Apptainer sandbox directory: {sandbox_path}")
        except Exception as e:
            print(f"Failed to remove Apptainer sandbox or base image file: {e}")
            logger.error(f"Failed to remove Apptainer sandbox or base image file: {e}")
            raise e