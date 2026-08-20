"""`python -m abt`, which the bundle's launcher shim invokes.

The shim cannot use the generated `abt` console script: that script carries an
absolute shebang pointing at whatever interpreter path existed when the wheel
was installed, which on a build runner is not a path that exists anywhere else.
"""

from .cli import app

app()
