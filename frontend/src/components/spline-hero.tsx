import Spline from "@splinetool/react-spline/next";

import { Card, CardContent } from "@/components/ui/card";

type SplineHeroProps = {
  sceneUrl?: string;
};

export function SplineHero({ sceneUrl = process.env.NEXT_PUBLIC_SPLINE_SCENE_URL }: SplineHeroProps) {
  return (
    <Card className="glass-panel min-h-[30rem] overflow-hidden">
      <CardContent className="relative flex min-h-[30rem] items-center justify-center p-0">
        {sceneUrl ? (
          <Spline scene={sceneUrl} className="min-h-[30rem] w-full" />
        ) : (
          <div className="relative flex size-full min-h-[30rem] items-center justify-center overflow-hidden p-8">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_35%,rgba(74,222,128,0.2),transparent_17rem)]" />
            <div className="absolute size-56 rounded-full border border-emerald-200/20 bg-emerald-300/10 shadow-2xl shadow-emerald-950/50" />
            <div className="absolute size-80 rounded-full border border-white/10" />
            <div className="absolute size-96 rounded-full border border-white/5" />
            <div className="relative max-w-xs text-center">
              <p className="text-sm font-medium uppercase tracking-[0.28em] text-emerald-200/80">
                Spline ready
              </p>
              <h2 className="mt-3 text-2xl font-semibold tracking-tight">Drop in a scene URL when polish begins.</h2>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                Set `NEXT_PUBLIC_SPLINE_SCENE_URL` to render a real Spline scene without changing the component contract.
              </p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
