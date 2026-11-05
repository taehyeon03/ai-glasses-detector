"""Product-specific reconstruction prompts based on the registered reference photos."""
import hashlib,json
VERSION='product_reference_details_v4_20261105'
DETAILS = {
    'Brilliant Labs Halo': 'Black softly rectangular full rims, clear lenses and a compact bridge. Keep the slender arms and blue sections with round attachments at the rear. Preserve the asymmetric optics without duplicating them.',
    'HTC VIVE Eagle': 'Charcoal full rims with rounded lower edges and a flattened brow. Keep the gray tinted lenses and the visible broad straight arm with its small downward ear tip. Keep the camera and indicator distinct.',
    'INMO GO3': "Black rectangular clear-lens frame with rounded lower corners and a short bridge. Keep the angular outer shoulders and the side arms' angled rear bends. Preserve the privacy cover and display optics at their reference positions.",
    'Mentra Live': 'Black clear-lens frame with angular outer shoulders and a shallow saddle bridge. The flat broad temple tapers into a curved ear tip. Preserve the actual outer-corner hardware.',
    'Oakley Meta HSTN': 'Dark rounded lenses in a thick black angular brow frame with a short straight bridge. Keep the two outer-corner features distinct as camera and indicator.',
    'Oakley Meta Vanguard': 'One smoke-gray wraparound shield under a broad curved brow. Keep the single camera below the top rim at the center above the nose opening and the separate lights. Match the wide sculpted arms and their rear accents.',
    'Ray-Ban Meta Gen 2 Headliner': 'Black rounded clear lenses with a relatively flat upper edge and a shaped bridge. Keep the thick outer shoulders and the distinct camera and capture indicator at their original corners.',
    'Ray-Ban Meta Gen 2 Skyler': 'Black upswept cat-eye rims with green lenses and a small saddle bridge. Keep the curved black temple tips. Preserve the camera and opposite capture indicator as separate features.',
    'Ray-Ban Meta Gen 2 Wayfarer': 'Black trapezoidal full rims with charcoal lenses and squared outer corners. Keep the short sculpted bridge and the separate camera and indicator at opposite upper outer corners.',
    'RayNeo X2': 'Thick black rounded-square front with clear lenses, a sculpted bridge and the visible display elements. Keep the outer housings. Do not copy rear arms seen through the product lenses as lens graphics.',
    'RayNeo X3 Pro': 'Black rounded-square clear-lens rims with a broad upper bridge assembly. Preserve the distinct apertures in the bridge and outer portions as documented, along with the lens display elements.',
    'Rokid AI Glasses Style': 'Dark lenses with rounded lower corners and a gray-black full rim. Keep the short light-gray bridge and the outer corner hardware distinct from the recording indicator.',
    'Rokid Glasses With Display': 'Black rectangular clear-lens rims with softly rounded bottoms and a short bridge. Keep the visible straight arms and downward tips. Preserve the actual camera and display optics. The additional reference is another front-biased view, and its award mark is outside the product.',
    'Solos AirGo V Krypton 1': 'Gray-black rectangular clear-lens rims and a short molded bridge. Keep the broad circular features at the two outer shoulders as shown, with the actual camera and LED in their documented roles.',
    'Solos AirGo V2 Prime 1': 'Black rectangular clear-lens rims with curved lower corners and a short molded bridge. Match the outer hinge housings and distinguish the existing camera from the LED.',
    'Xiaomi AI Glasses': 'Black angular full rims with clear lenses and a compact bridge. Keep the dark wide hinge region and curved arm tips visible in the references. Preserve the single real camera and separate light.',
    'Amazon Blue Light Glasses Men Rectangle Large Browline Computer Gaming Glasses': 'Thick black upper brow over a fine lower rim around rectangular clear lenses. Keep the separate pads, narrow arms and blue inner tip accents visible in the reference.',
    'Amazon Dollger Rectangle Blue Light Glasses for Men Metal Fashion Small Half Frame': 'Gold wire-like upper half rims over shallow rectangular clear lenses with exposed lower edges. Keep the separate pads, fine gold arms and black ear tips.',
    'Amazon Ray-Ban RX5154 Clubmaster Square Eyeglasses for Men for Women': "Black browline with a fine gold lower rim, gold bridge and clear pads. Keep the small flat front decorations and the reference's squared lens shape.",
    'Amazon Ray-Ban Unisex Rx7216 New Clubmaster Square Prescription Eyewear Frames': 'Black squared brow pieces with a silver-colored bridge and fine pale lower rims. Keep the small corner rivets flat and retain clear lenses and separate pads.',
    'Amazon Shiratori Retro Eyebrow Frame Glasses for Men, Semi-Rimless Blue Light Blocking Glasses, Anti Blue Light Computer Glasses': 'Black flat brow pieces over rounded rectangular clear lenses. Preserve the fine pale lower edges, thin metal bridge, separate pads and narrow dark arms.',
    'Amazon Titanium Rimless Round Reading Glasses Blue Light for Men Women': 'Round rimless clear lenses held by small screws. Keep the slender silver bridge, separate pads and delicate curved wire-like arms.',
    'Amazon Titanium Semi Rimless Prescription Glasses Frame For Men,Ultra Lightweight Optical Eyewear Frames Demo Lens 53mm': 'Thin dark upper rims over rectangular clear lenses with exposed lower edges. Keep the fine bridge, separate pads and thin arms with dark bent tips.',
    'DIFF AVA - LIGHT PINK CRYSTAL + BLUE LIGHT READERS': 'Translucent pale pink rounded-square full rims and clear lenses. Keep the narrow matching translucent arms, small visible hinges and gentle rear bends.',
    'DIFF CAMERON - RICH RED TORTOISE + GREY GRADIENT + POLARIZED + SUNGLASSES': 'Deep red tortoiseshell aviator front with a double bridge, broad angular lenses and dark-to-light gray gradient. Keep the red patterned arms slim and tapering.',
    'DIFF CINDERELLA - BLUE CRYSTAL GLITTER + GLASSES': 'Pale translucent glitter-blue full rims with raised outer corners and clear lenses. Keep the slender metal-colored arms and the blue sleeves at their bent ends.',
    'DIFF CONNIE - GOLD + BLUE LIGHT GLASSES': 'Fine gold angular rims, one thin bridge, clear lenses and separate pads. Keep the slender gold arms with pale hooked tips.',
    'DIFF EMERSON - GOLD + BLUE LIGHT GLASSES': 'Fine gold rounded aviator rims with a distinct straight upper brow bar over the bridge. Keep the clear pads and slender gold arms with pale rear tips.',
    'DIFF HAILEY - CREAM TORTOISE + SOLID GREY SUNGLASSES': 'Thick cream-and-brown tortoiseshell rims with upswept outer corners and solid gray lenses. Keep the slender gold arms and matching tortoiseshell tips.',
    'DIFF JADE - AQUA SEA CRYSTAL + BLUE LIGHT GLASSES': 'Pale translucent aqua rims with soft upswept outer corners and clear lenses. Preserve the narrow bridge and small solid hinge details.',
    'DIFF JORDAN - POWDER PINK + GOLD + BROWN GRADIENT SUNGLASSES': 'Powder-pink squared aviator rims with a thin upper bar and brown gradient lenses. Keep the fine gold-colored arms and pale pink curved tips visible in the oblique reference.',
    'DIFF MEREDITH - DARK TEAL + GLASSES': 'Thick dark-teal full rims with a raised outer brow and angular lower corners. Keep the broad teal arm taper, bent ear tip and small flat lettering.',
    'DIFF PARKER - DARK TEAL + BLUE LIGHT GLASSES': 'Teal rounded-rectangular clear-lens rims with a flatter brow and slimmer lower edges than Meredith. Keep the slim rectangular teal arm, taper and flat lettering.',
    'DIFF RIP WHEELER - WESTERN GOLD + GLASSES': 'Gold squared aviator wire rims with a double bridge, separate pads and clear lenses. Keep the thin gold arms and dark brown bent ear tips.',
    'DIFF THE DUTTON - SEQUOIA TORTOISE + GLASSES': 'Thick brown tortoiseshell full rims with a low saddle bridge and flat silver corner rivets. Keep the patterned arms broad at the hinge and tapered at the bent tips.',
    'Oakley Eye Jacket Redux OO9438-0158': 'Black narrow oval wraparound rims with subdued gray-purple lenses. Keep the short bridge mark and curved black tapered arms with a flat oval emblem.',
    'Oakley Gascan OO9014': 'Black rectangular wraparound full rims with dark gray lenses. Keep the broad flat arms with straight upper edges, tapered lower edges and flat elongated oval badges.',
    'Oakley HSTN SQ OX8208': 'Dark blue upper brow over translucent blue angular lower rims with clear lenses. Preserve the narrow horizontal opening between the two bridge bars. Each wide front temple narrows into a translucent blue dogleg immediately behind the hinge section, dips and rises, then curves down behind the ear. The silver plate with the small black oval sits flush on the outer temple before the dogleg. Keep it off the front rim.',
    'Oakley Hex Jector OX8032': 'Clear angular front with clear lenses and a dark nose insert. Keep the transparent hinge region, slim yellow tapered temple sections and flat oval side emblem.',
    'Ray-Ban New Wayfarer RB2132': 'Black rounded trapezoidal full rims with subdued green lenses. Keep flat elongated silver front rivets and tapered black temples with curved tips.',
    'Ray-Ban Original Wayfarer Optics RX5121F': 'Black angular full rims around clear lenses, with a sculpted bridge and flat horizontal silver front rivets. Keep the black arms tapering into downward rear bends.',
    'Ray-Ban RB2140 Original Wayfarer Classic 901': 'Black bold trapezoidal rims with dark green lenses and a broad upper brow. Keep the small flat silver corner rivets and broad black temple bases tapering toward the tips.',
    'Ray-Ban Wayfarer Deluxe Optics RX3875V': 'Fine gold lower rim with a thicker flat gold brow and separate clear pads. Keep the flat gold temple plates that taper into black rear tips and the small flat markings.',
    'Ray-Ban Wayfarer Ease RB4340': 'Black softly squared full rims with dark green lenses and a shaped bridge. Keep the small flat silver horizontal front rivets and broad black temple bases tapering into curved tips.',
    'goodr Darkwood Coffee Ritual': 'One muted-green wraparound shield with a slim brown upper rail and exposed lower lens edge. Keep the separate nose pads and brown arms that widen toward the front, then narrow at the tips.',
    'BLUE_ELEPHANT ANDY black': 'Black rounded-square full rims with flared outer corners and a low bridge. Keep the slim black temples and sharply bent tips.',
    'BLUE_ELEPHANT AVA black': 'Black narrow oval rims that taper slightly at the outer edges. Keep the thick hinge section narrowing into a thin black arm.',
    'BLUE_ELEPHANT BRANDON-N2 crystal': 'Clear angular full rims and a transparent short bridge. Keep the slim translucent temples and visible solid hinge hardware.',
    'BLUE_ELEPHANT EDIE black': 'Black rounded panto rims with a compact bridge and pointed outer shoulders. Keep the slim straight arms and bent tips.',
    'BLUE_ELEPHANT FLEEK black': 'Rimless clear lenses with small dark end fittings and a narrow dark bridge. Keep the wire-thin black arms and separate nose pads.',
    'BLUE_ELEPHANT GOAT black': 'Thin black upper rims over shallow rectangular clear lenses. Keep the narrow nose bridge and two fine arms with black tips.',
    'BLUE_ELEPHANT IKER gold': 'Clear rimless lenses with small gold-colored mounts and a narrow gold bridge. Keep the slim pale gold arms and transparent tips.',
    'BLUE_ELEPHANT JAMIE black': 'Thick black shallow rectangular rims with rounded lower corners. Keep the very fine light-colored temples and black curved tips.',
    'BLUE_ELEPHANT REI black': 'Fine black rounded-square metal rims and a narrow bridge. Keep the slim dark arms and subtle rear bends.',
    'BLUE_ELEPHANT RISA black': 'Thick black shallow rectangular full rims with broad outer edges. Match the wide temple base and its smooth curve into the rear tip.',
    'BLUE_ELEPHANT RIZZ black': 'Clear rimless lenses with dark mounting fittings. Preserve the thin dark bridge, nose pads and delicate straight temples.',
    'BLUE_ELEPHANT SASHA black': 'Black narrow almond-shaped rims with pointed outer corners. Keep the slim tapered dark arms and sharp rear bends.',
    'MANOMOS GEORGE TITANIUM  53 C1': 'Dark round rims with slightly raised outer corners and a narrow light-colored bridge. Keep the fine dark arms and their short bent tips.',
    'MANOMOS RYU C1': 'Fine black oval full rims and a thin bridge. Keep the narrow black arms with small downturned tips.',
    'MANOMOS HAN C1': 'Black broad rectangular rims with a flat brow and a narrow upper bar above the bridge. Keep slim dark temples and angled tips.',
    'MANOMOS KWON C1': 'Black narrow angular rectangular rims and a low bridge. Keep the compact outer shoulders and tapered straight arms.',
    'MANOMOS ANNI C1': 'Fine dark softly rounded rims with slightly raised shoulders. Keep the narrow bridge and very slender dark arms.',
    'MANOMOS MOMEN C1': 'Dark thin trapezoidal full rims with a flat brow and shallow bridge. Keep the fine straight temples and small tips.',
    'MANOMOS REMI C1': 'Black angular full rims with flared outer corners and a shallow curved bridge. Keep the slim temples and short downward tips.',
    'MANOMOS OCCA C1': 'Dark softly hexagonal rims with tapered lower corners and a thin bridge. Keep the fine arms and bent tips.',
    'MANOMOS PRESI C1': 'Dark rounded-square full rims with a flat upper brow and defined outer corners. Keep the narrow bridge and thin temples.',
    'CARIN AIR 3 A_C2': 'Warm brown rounded-square rims. Keep the narrow brown bridge, very slender metallic arms and reddish brown bent tips.',
    'CARIN AIR 3 R_C1': 'Black round full rims and a compact dark bridge. Keep the fine metallic arms with black downturned sleeves.',
    'CARIN AIR 3 O_C2': 'Light warm brown softly oval rims. Keep the thin metallic arms and matching warm brown bent tips.',
    'CARIN AIR 3 S_C3': 'Gray-black rectangular rims with a straight upper edge and rounded lower corners. Keep the fine arms and gray tips.',
    'CARIN ROY O_C3': 'Dark tortoiseshell oval rims and a compact bridge. Keep the thin light-colored metal arms and narrow bent tips.',
    'CARIN ROY S_C3': 'Dark gray softly squared full rims. Keep the slim metallic temples and the fine downward sweep of their tips.',
    'CARIN ROY R_C3': 'Dark tortoiseshell round rims with amber patches. Keep the very fine light metal arms and narrow bent tips.',
    'CARIN ROY A_C4': 'Amber-brown rounded-square rims and a compact bridge. Keep the slim metal arms and their light-colored tips.',
    'CARIN ROY P_C1': 'Black softly rounded panto rims with slightly raised corners. Keep the narrow dark metal temples and short downturned tips.',
    'CARIN ROY C_C4': 'Pale translucent pink rounded-square rims and a fine bridge. Keep the pale fine metal arms and narrow curved tips.',
    'CARIN RONENN B_C1': 'Black narrow upswept rectangular rims and a low dark bridge. Keep the thin arms and black curved rear sleeves.',
    'CARIN ARNO N_C2': 'Dark reddish-brown narrow oval rims with raised outer ends. Keep the matching warm brown temples and downturned tips.',
}

def apply_fidelity(condition):
 con=dict(condition)
 if con.get('kind')!='tryon':return con
 extras=con.get('extra_references',[])
 parts=['Edit image 1. Preserve this exact adult identity and head direction. Fit ONE pair of the exact manufactured glasses from the product references. Reconstruct this physical product without redesigning it.',
 'Image 2 is the primary product reference and controls the front rim outline, lens shape, bridge, nose pads, color, transparency and tint. Match the lens aspect ratio, rim thickness and bridge width.']
 if extras and con.get('product')=='Rokid Glasses With Display':
  parts.append('Image 3 is a second front-biased reference. Use it only for visible geometry. Keep undocumented side surfaces plain.')
 elif extras and extras[0].get('role')=='oblique':
  parts.append('Image 3 is an oblique view of the same product. Preserve the visible temple taper, hinge and decoration in perspective. Do not treat foreshortened widths as direct side measurements.')
 elif extras:
  parts+=['Image 3 shows the SAME product from the side. Use it as the geometry authority for the temple, hinge and every decoration. Match the temple height relative to the lens height at the hinge, its complete upper and lower contours, taper, bends, cross-section and rear tip. Keep the side badge shape, size, color, relief, order and distance from the hinge. Account only for perspective and foreshortening; do not thicken or slim the physical arm.']
 else:parts+=['Use only the documented product views. Keep any side portions that are not shown in the reference plain and minimal. Do not invent their decorations.']
 if con.get('camera')=='absent':
  parts+=['This is ordinary non-electronic eyewear with ZERO imaging apertures. Its frame surfaces are solid acetate or metal as shown. Rivets, screws, oval badges and printed marks remain flat solid hardware or decoration. No black glass circles, concentric optical rings, dark hollow openings, projecting sensor pods or lights may be added.']
 else:
  parts+=['Reproduce only the real imaging apertures that are visible in the product references, at their exact documented positions and sizes. Distinguish a solid rivet or badge from an aperture. Keep lights as lights. Do not copy any electronic part to the opposite side.']
 parts+=['Open the real hinges for normal wear. Each unchanged rigid temple runs backward over its corresponding ear. Arms seen folded behind the product lenses are movable arms, NOT diagonal lens stripes or objects to paste across the face. Preserve the original lens opacity and transmission; eyes must not appear through opaque sunglass lenses.',
 'If one side is documented and the opposite side is not, assume left-right symmetric STRUCTURAL hinge and temple geometry for the opposite side. Apply that assumption to the contour and decorative shape only. Never mirror readable lettering or duplicate or relocate electronic components. Show only the near-side parts physically visible at the requested angle.']
 if con.get('product') in DETAILS:parts.append(DETAILS[con['product']])
 feedback=con.get('regeneration_notes','').strip()
 if feedback:parts.append('Human correction to honor: '+feedback)
 parts+=['Face-only close-up. Keep the full visible glasses and hinge sharp and inside the picture. Crop below the chin, with no shoulders or torso. About 10 percent of the picture is background. Keep hair off the hinges. Natural skin, normal optical detail, no extra text, comparison panels or new decorative markings.']
 from ai_glasses.generation.face_framing import BACKGROUNDS,LIGHTING
 key=json.dumps([con.get('person_id'),con.get('pose'),con.get('seed',0)],ensure_ascii=False);v=int(hashlib.sha256(key.encode()).hexdigest(),16)
 bg=BACKGROUNDS[v%len(BACKGROUNDS)];light=LIGHTING[(v//len(BACKGROUNDS))%len(LIGHTING)]
 parts.append('Small realistic background margins: '+bg[1]+'. Lighting: '+light[1]+'. Background and reflections must leave all physical frame details unchanged.')
 con.update(prompt=' '.join(parts),product_fidelity_version=VERSION,background_style=bg[0],lighting_variant=light[0],fidelity_verified=False)
 return con
