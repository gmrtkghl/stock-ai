import sys, types, unittest

class Session(dict):
    __getattr__ = dict.get
    def __setattr__(self, k, v): self[k] = v

stub = types.SimpleNamespace(session_state=Session())
sys.modules.setdefault('streamlit', stub)

import cloud_storage as cs

class StorageParseTests(unittest.TestCase):
    def test_default(self):
        state = cs._parse(None)
        self.assertEqual(state['schema_version'], 1)
        self.assertIn('005930.KS', state['watchlist']['symbols'])

    def test_invalid_symbols_filtered(self):
        state = cs._parse({'schema_version':1,'watchlist':{'symbols':['AAPL','bad space','^GSPC'],'meta':{}},'positions':{}})
        self.assertEqual(state['watchlist']['symbols'], ['AAPL','^GSPC'])

if __name__ == '__main__': unittest.main()
