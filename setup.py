from setuptools import setup, find_packages

setup(
    name="dpms",
    version="1.1.0",
    author="Archit & Kevin (THE Discovery Team)",
    description="Discovery Package Manager (DPMS) - cross-platform CLI, TUI & GUI package manager",
    long_description=open("README.md", "r", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/discoveryos/dpms",
    packages=find_packages(include=["dpms", "dpms.*"]),
    include_package_data=True,
    install_requires=[
        "requests",
        "rich",
        "textual",
        "tqdm",
    ],
    extras_require={
        "gui": ["PyQt5"],
    },
    entry_points={
        "console_scripts": [
            "dpms=dpms.dpms:main",
            "dpms-tui=dpms.dpms_tui:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Environment :: Console",
        "Environment :: X11 Applications :: Qt",
        "Topic :: System :: Archiving :: Packaging",
    ],
    python_requires=">=3.8",
)
