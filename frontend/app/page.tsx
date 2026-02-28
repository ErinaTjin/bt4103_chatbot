import { redirect } from "next/navigation";

// Redirect root to chat page
export default function Home() {
  redirect("/chat");
}
