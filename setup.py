from setuptools import setup, find_packages

setup(
    name="harnessNovel",
    version="0.1.4",
    author="飞鸟 one the way",
    description="长篇网络小说写作 AI Agent",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/XTmingyue/harnessNovel",
    license="GPL-3.0",
    packages=find_packages(),
    py_modules=["novel_cli"],
    package_data={
        "core": ["prompts/*/prompt.txt"],
    },
    entry_points={
        "console_scripts": [
            "novel=novel_cli:main",
        ],
    },
    install_requires=[
        "openai",
    ],
    python_requires=">=3.9",
)
