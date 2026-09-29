"""CogTool-Py research prototype. No original-program equivalence is claimed."""

__version__ = "0.2.1rc1"
ENGINE_VERSION = "0.2.0"
UPSTREAM_COMMIT = "a91d91e8dcf95d762b6e08020029a36ea079bbba"
UPSTREAM = {
    "repository": "https://github.com/cogtool/cogtool",
    "tag": "1.3-2014-02-10",
    "commit": UPSTREAM_COMMIT,
}


def source(path: str, symbol: str) -> str:
    return f"{UPSTREAM['repository']}@{UPSTREAM_COMMIT}:{path}:{symbol}"


JAVA_MODEL = "java/edu/cmu/cs/hcii/cogtool/model/"
GENERATOR = JAVA_MODEL + "KLMCognitiveGenerator.java"
