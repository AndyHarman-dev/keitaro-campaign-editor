import { Route, Routes } from 'react-router-dom'
import CampaignsScreen from './screens/CampaignsScreen'
import EditorScreen from './screens/EditorScreen'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CampaignsScreen />} />
      <Route path="/campaigns/:id" element={<EditorScreen />} />
    </Routes>
  )
}
