from setuptools import setup, find_packages

setup(
    name="bonk_game",
    version="0.0.2",
    packages=find_packages(exclude=["tests"]),
    # Exact versions are pinned in requirements.txt; these just need to agree with it
    install_requires=["gym==0.21.0", "pygame>=2.1.0", "numpy"],
)
