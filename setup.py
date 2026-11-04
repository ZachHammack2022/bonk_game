from setuptools import setup, find_packages

setup(
    name="bonk_game",
    version="0.1.0",
    packages=find_packages(exclude=["tests"]),
    package_data={"bonk_game": ["maps/*.json", "server/static/*", "server/static/js/*",
                                "server/static/vendor/*"]},
    python_requires=">=3.10",
    # The game itself only needs these; training also needs
    # stable-baselines3 and sb3-contrib (see requirements.txt).
    install_requires=["numpy>=1.24", "pygame>=2.1", "gymnasium>=0.29", "Box2D>=2.3.10"],
    # The web server: pip install -e ".[server]"
    extras_require={"server": ["aiohttp>=3.9", "authlib>=1.9", "httpx2>=2.13", "better-profanity>=0.7"]},
)
