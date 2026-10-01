from setuptools import setup, find_packages

setup(
    name="shade-protocol",
    version="1.0.0",
    description="SHADE: Shadow-Hedged Auction with Decaying Estimates - Decentralized Task Allocation Protocol",
    author="Autonomous Systems Fleet Team",
    packages=find_packages(),
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "shade=shade.cli:main",
        ],
    },
)
