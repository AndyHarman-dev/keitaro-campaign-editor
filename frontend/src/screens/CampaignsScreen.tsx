import CampaignList from '../components/CampaignList'
import ConnectionBadge from '../components/ConnectionBadge'
import NewCampaignForm from '../components/NewCampaignForm'

export default function CampaignsScreen() {
  return (
    <div className="page">
      <header className="topbar">
        <span className="brand">Campaign Editor</span>
        <ConnectionBadge />
      </header>
      <main className="campaigns-layout">
        <CampaignList />
        <NewCampaignForm />
      </main>
    </div>
  )
}
