# Ragaz

[![CircleCI](https://dl.circleci.com/status-badge/img/gh/ragazzi-robotics/ragaz/tree/main.svg?style=svg)](https://dl.circleci.com/status-badge/redirect/gh/ragazzi-robotics/ragaz/tree/main)  [![Coverage Status](https://coveralls.io/repos/github/ragazzi-robotics/ragaz/badge.svg?branch=main)](https://coveralls.io/github/ragazzi-robotics/ragaz?branch=main)

Ragaz is a fast, safe and powerful pythonic compiler which aims allow you to create simple scripts to complex systems 
in a code easier to read, write and maintain than other system languages with the same purpose.

See a *hello world* in Ragaz:

    def main():
        print("Hello World")

To compile, just run the following:
    
    ragazc compile examples/hello_world.zz
    
    # output: 
    Hello World

In short words, Ragaz is a dialect of Python with features that allow your pythonic code run on bare metal. This 
is possible because the compiler converts Ragaz code to binaries using LLVM as intermediate language.

## Getting Started

The learning curve for Ragaz is very smooth. We invite you to check our [Get Started](./doc/user/tutorial.md) 
guide. We believe that in a short time you will have a good clue about the Ragaz works.

## Installation

Ragaz works on:

- Linux x86 and 64bit
- Windows (partially: **try/except** statements are failing because compiler's error handling need be updated to 
- support Windows)

And have the following dependencies:

- [Python](https://www.python.org/) (3.9 or later)
- [LLVM/Clang](https://llvm.org/) (11.0 or later)

To install Ragaz, download and open the repository and just run the following:

    python setup.py install

## Test

To check whether installation was successful, just run the following:

    # From the root of the repo:
    python test.py

## How to contribute

If you liked the projet and would like accelerate the Ragaz development, we will appreciate your finantial support in order
to we dedicate full time to this project with no distractions. We also welcome companies that wish sponsor the project.

https://www.patreon.com/RagazLang/

If you are a developer, any help is welcome to our project. Contributions include since developing new features, bug fixes 
and refactoring until write documentation and manage tools like git and build artefacts. You can start reading the 
[documentation](./doc/user/tutorial.md) to be familiar with the code and check the list of issues to see which interest you 
and then pick it.

## FAQ

**Is my Python module compatible to Ragaz?**

Although Ragaz try to be the closest possible to original Python language unfortunately some default Python features 
won't fit the Ragaz purpose, and thus you'll find some strict rules not present on default Python language and even 
will find new features like variable mutability and borrowing present in languages like Rust.
Thus, all will depend on your code. When you import pure Python modules into a Ragaz module, Ragaz will try 
to compile them. If there is any code that is not accepted on Ragaz, errors will be emitted by the compiler. But don't 
worry, the adaptation from Python to Ragaz code is not a hard job and the compiler will be your friend.

**Is Ragaz really fast?**

Compared to other pyhtonic tools, Ragaz is faster than many of them because these tools try to keep compatibility 
to Python code that is very high level but not much efficient, this force they to use a lot de 
overload to create automatic conversions among other drawbacks. Ragaz doesn't worry about keep compatibility 
with all Python features rather it forces user to strictly type her variables, encapsulate code into functions, 
discard garbage collection, etc. As a result user has a code that is straight-forward and thus fast because it 
uses fewer instructions to run.
See our examples comparing performance of Ragaz with other Python-derived interpreters and compilers.

Even when compared to system languages like C/C++, Rust, etc, Ragaz has a pretty similar performance as you even
can using our benchmarking examples.

**Can I import modules compiled by other languages like C, C++ or Rust?**

Yes, of course! You declare these modules on dependencies file and then normally import these on your Ragaz file
as if they were Python modules.

**Can I have parallelism using multiprocessing with Ragaz?**

Yes! As Ragaz doesn't use GIL (Global Interpreter Lock) your code can simultaneously run in multiple processors.
