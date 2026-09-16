import { Link } from "react-router-dom";
import { Button } from "../components/ui/Button";

export default function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="font-display text-6xl text-coral">404</div>
      <p className="text-ink-soft">That page doesn't exist here.</p>
      <Link to="/">
        <Button>Back to Projects</Button>
      </Link>
    </div>
  );
}
