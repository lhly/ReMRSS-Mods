// Public worker ABI: this source is passed to the isolated runtime as one file.
globalThis.__remrss = {
  init() { return { count: 0 }; },
  reduce({ state, event }) {
    if (event.type === "counter.increment") return { state: { ...state, count: state.count + 1 } };
    if (event.type === "counter.decrement") return { state: { ...state, count: state.count - 1 } };
    return { state };
  }
};
