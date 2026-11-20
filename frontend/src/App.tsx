import { Route, Routes } from 'react-router-dom'
import CampaignsScreen from './screens/CampaignsScreen'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CampaignsScreen />} />
    </Routes>
  )
}
