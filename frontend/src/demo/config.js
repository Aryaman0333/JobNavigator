// Demo build switches. __DEMO__ is defined by vite.config.js (VITE_DEMO=1).
export const IS_DEMO = typeof __DEMO__ !== 'undefined' && __DEMO__ === true
export const ROUTER_BASENAME = IS_DEMO ? '/JobNavigator' : undefined
