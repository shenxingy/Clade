#!/usr/bin/env python3
"""
Environment Setup for Blog Google Skill
Manages virtual environment and dependencies automatically
"""

import os
import sys
import subprocess
import venv
from pathlib import Path


class SkillEnvironment:
    """Manages skill-specific virtual environment"""

    def __init__(self):
        self.skill_dir = Path(__file__).parent.parent
        self.venv_dir = self.skill_dir / ".venv"
        self.requirements_file = self.skill_dir / "scripts" / "requirements.txt"

        if os.name == 'nt':
            self.venv_python = self.venv_dir / "Scripts" / "python.exe"
            self.venv_pip = self.venv_dir / "Scripts" / "pip.exe"
        else:
            self.venv_python = self.venv_dir / "bin" / "python"
            self.venv_pip = self.venv_dir / "bin" / "pip"

    def ensure_venv(self) -> bool:
        """Ensure virtual environment exists and is set up"""
        if self.is_in_skill_venv():
            return True

        if not self.venv_dir.exists():
            print(f"Creating virtual environment in {self.venv_dir.name}/")
            try:
                venv.create(self.venv_dir, with_pip=True)
            except Exception as e:
                print(f"Failed to create venv: {e}")
                return False

        if self.requirements_file.exists():
            print("Installing dependencies...")
            try:
                subprocess.run(
                    [str(self.venv_pip), "install", "--upgrade", "pip"],
                    check=True, capture_output=True, text=True,
                )
                subprocess.run(
                    [str(self.venv_pip), "install", "-r", str(self.requirements_file)],
                    check=True, capture_output=True, text=True,
                )
                print("Dependencies installed")
                return True
            except subprocess.CalledProcessError as e:
                print(f"Failed to install dependencies: {e}")
                return False
        else:
            print("No requirements.txt found, skipping dependency installation")
            return True

    def is_in_skill_venv(self) -> bool:
        """Check if running in the skill's venv"""
        if hasattr(sys, 'real_prefix') or (
            hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix
        ):
            return Path(sys.prefix) == self.venv_dir
        return False

    def get_python_executable(self) -> str:
        """Get the correct Python executable"""
        if self.venv_python.exists():
            return str(self.venv_python)
        return sys.executable


def main():
    """Main entry point for environment setup"""
    import argparse

    parser = argparse.ArgumentParser(description='Setup Blog Google skill environment')
    parser.add_argument('--check', action='store_true', help='Check if environment is set up')
    args = parser.parse_args()

    env = SkillEnvironment()

    if args.check:
        if env.venv_dir.exists():
            print(f"Virtual environment exists: {env.venv_dir}")
            print(f"   Python: {env.get_python_executable()}")
        else:
            print("No virtual environment found")
        return

    if env.ensure_venv():
        print(f"\nEnvironment ready!")
        print(f"   Virtual env: {env.venv_dir}")
        print(f"   Python: {env.get_python_executable()}")
    else:
        print("\nEnvironment setup failed")
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
