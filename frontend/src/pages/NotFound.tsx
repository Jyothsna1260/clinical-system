import { Link } from "react-router-dom";
import { ROUTES } from "../lib/routes";

export default function NotFound() {
  return (
    <div className="card mx-auto max-w-lg p-8 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-slate-600">The page you requested does not exist.</p>
      <Link to={ROUTES.dashboard} className="btn-primary mt-6">
        Go to dashboard
      </Link>
    </div>
  );
}
