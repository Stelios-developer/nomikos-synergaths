// Either production flag enables ALL production safeguards. They must never
// disagree about binding, cookies, or verification requirements.
export function isProductionEnvironment(env: NodeJS.ProcessEnv = process.env): boolean {
  return [env.APP_ENV, env.NODE_ENV].some(value => value?.trim().toLowerCase() === 'production');
}

export const isProduction = isProductionEnvironment();
