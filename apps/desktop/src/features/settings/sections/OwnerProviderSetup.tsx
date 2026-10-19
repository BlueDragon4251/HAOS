import { IconCpu, IconLock, IconShieldCheck } from '@tabler/icons-react'

/** The unprivileged observer must never generate shell scripts to acquire
 * owner secrets. Those operations move to a separate native root-only graphical
 * setup seat; keep its stage clear while that seat is not boot-qualified.
 */
export function OwnerProviderSetup() {
  return (
    <div className="space-y-3 rounded-xl border border-line bg-white/3 p-4 text-[12px]">
      <div className="flex items-center gap-2 font-semibold text-fg">
        <IconCpu size={17} className="text-accent" />
        Hermes · Provider und Modelle
      </div>
      <div className="text-fg-2 leading-relaxed">
        HAOS unterstützt bereits einen geschützten einzelnen Modellprovider.
        Die Auswahl mehrerer Provider und die automatische Modellauswahl
        werden mit dem separaten Administrator-Setup integriert. Das bisherige
        Kopieren von Root-Befehlen ist kein Bestandteil des neuen grafischen Setups.
      </div>
      <div className="flex items-start gap-2 rounded-lg border border-line px-3 py-3">
        <IconLock size={17} className="mt-0.5 shrink-0 text-fg-2" />
        <div className="space-y-1">
          <div className="font-semibold text-fg">Administratorfreigabe erforderlich</div>
          <p className="text-fg-3">
            Zugangsdaten werden ausschließlich in der eigenen geschützten
            lokalen Administrator-Oberfläche eingegeben. Solange deren echter
            Erststart noch nicht getestet wurde, kann dieser normale Desktop
            keine geheimen Provider-Schlüssel ändern.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 text-fg-3">
        <IconShieldCheck size={15} />
        Kein API-Schlüssel im Desktop, Browser oder Hermes-Protokoll
      </div>
    </div>
  )
}
