import { LoginForm } from "@/components/login-form"
import { TulipIllustration } from "@/components/tulip-illustration"

export default function LoginPage() {
  return (
    <main className="min-h-screen bg-[#FFF8E7] flex items-center justify-center p-4 sm:p-6 lg:p-8 relative overflow-hidden">
      <div className="hidden md:block absolute top-8 left-8 opacity-15">
        <TulipIllustration size="small" />
      </div>
      <div className="hidden md:block absolute bottom-8 right-8 opacity-15 rotate-180">
        <TulipIllustration size="small" />
      </div>
      <div className="hidden lg:block absolute top-1/4 right-12 opacity-10">
        <TulipIllustration size="small" />
      </div>
      <div className="hidden lg:block absolute bottom-1/4 left-12 opacity-10 rotate-12">
        <TulipIllustration size="small" />
      </div>

      <div className="w-full max-w-sm sm:max-w-md relative z-10">
        <LoginForm />
      </div>
    </main>
  )
}
