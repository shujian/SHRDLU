"""SHRDLU: a two-program test bed for "understanding a limited world".

The system is two independent programs that talk in text:

``shrdlu-env``
    Holds the **true** world state.  Loads a scenario, runs the match in three
    stages -- questions, instructions, the same questions again -- keeping a
    **second** state that follows the testee's calls beside the scripted truth,
    grades each stage on its own and records the match.

``shrdlu-testee``
    The party under judgement.  Keeps its **own** model of the world, parses
    the English it is sent, decides whether an instruction is legal, and
    answers the questions.

They share this package's world model, snapshot format, operation rules and
wire protocol, but never share state: the env side lives in ``shrdlu.env``, the
testee side -- the interface and a minimal example -- in ``shrdlu.testee``.  The testee never sees the truth: it is told the initial
scene once -- and is never given either of the env's two states again -- and
must work the rest out from its own understanding.

Design documents: the front page is ``README.md`` (world, division of labour and
project layout, decisions); the usage manual is ``README-env.md``.  The rest
lives in ``docs/`` (public: 设计协议, env功能介绍, testee开发需求) and
``docs/develop/`` (private: 开发进度, 需求记录, 设计评审, SHRDLU原始问句集)::

* ``README.md``           -- what we are building, and the decisions behind it
* ``README-env.md``       -- how to run the seven programs
* ``docs/设计协议.md``    -- the wire format, in full
* ``docs/env功能介绍.md`` -- what the env offers and guarantees (for its users)
* ``docs/testee开发需求.md`` -- the contract for anyone writing a testee
* ``docs/develop/开发进度.md`` -- how it was built, what comes next (private)
* ``docs/develop/SHRDLU原始问句集.md`` -- what the original SHRDLU handled (private)
"""

__version__ = "0.2.0"
