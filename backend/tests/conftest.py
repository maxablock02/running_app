import os
import tempfile

# One throwaway database for the whole test session (the engine is created once
# at import). Test modules use distinct activity ids so they don't collide.
os.environ["RUNNING_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
