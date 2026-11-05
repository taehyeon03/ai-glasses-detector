"""Validate product-side references and describe the image roles explicitly."""
from pathlib import Path
from PIL import Image,ImageOps
from ai_glasses.generation import tryon_lab as lab
import re

HINGE_VERSION='reference_hinge_contralateral_symmetry_v1'

def apply_hinge_condition(condition):
    con=dict(condition)
    if con.get('kind')!='tryon' or not con.get('prompt'):return con
    prompt=re.sub(r'\s*\[HINGE_POLICY_BEGIN\].*?\[HINGE_POLICY_END\]','',con['prompt'],flags=re.S)
    roles=[r.get('role') for r in con.get('extra_references',[]) if r.get('role') in ('left_side','right_side')]
    orientation=(' The provided side reference shows the '+roles[0].replace('_',' ')+' of the product.') if len(set(roles))==1 else ''
    prompt+=(' [HINGE_POLICY_BEGIN] Match the hinge in the product references exactly: its silhouette, attachment position, joint axis, visible screw positions, material, color and transition into the temple. '
        'Preserve the referenced temple thickness, curvature and structural detailing.'+orientation+
        ' When only one physical side is shown and the requested face view reveals the opposite side, assume the opposite hinge and structural temple geometry are left-right symmetric, as requested by the user. '
        'Construct that opposite side by reflecting the referenced structure into the correct physical position on the face. Do not invent a different hinge design or temple shape. '
        'This explicit structural symmetry assumption overrides earlier instructions that leave unseen hinge or temple geometry unspecified. '
        'Preserve normal unfolded wearing articulation at the actual hinge. '
        'Do not mirror the entire product photograph. Do not duplicate or relocate cameras, status lights, sensors, microphones or buttons; retain their documented physical sides and counts. '
        'Do not reverse readable lettering. If the real opposite side is shown in another reference, follow that direct evidence for its actual details. [HINGE_POLICY_END]')
    con.update(prompt=prompt,hinge_fidelity_version=HINGE_VERSION,contralateral_structure_policy='assume_symmetric_when_opposite_side_not_shown',hinge_reference_sides=sorted(set(roles)),hinge_assumption_verified=False)
    return con

def append_references(images,condition):
    extras=condition.get('extra_references',[])
    if len(extras)>1:raise ValueError('Use one side view in addition to the face and front view')
    for reference in extras:
        if reference.get('product')!=condition.get('product'):raise ValueError('The side reference must depict the same product')
        if reference.get('role') not in ('left_side','right_side','side','oblique'):raise ValueError('Specify a supported product view')
        path=Path(reference['path'])
        if lab.digest(path)!=reference['sha256']:raise ValueError('Additional reference bytes changed')
        im=ImageOps.exif_transpose(Image.open(path)).convert('RGB');im.thumbnail((1024,1024));images.append(im)
    return images

def prompt_for_views(prompt,extras):
    if not extras:return prompt
    guidance=' Reference image roles: image 1 is the adult identity and the required tight face composition. Image 2 is the FRONT view of the real glasses. Image 3 is the SIDE view of the SAME glasses. Use image 2 for the frontal frame outline, lenses, bridge, front-facing camera apertures and indicator lights. Use image 3 for the temples, hinges, thickness, curvature, side buttons, side logos and camera-module housing. Both product views depict the same articulated product. Keep each rigid frame and temple component unchanged while opening the actual hinges for wear. Do not combine them into two frames, add a second pair, mirror a camera, or duplicate buttons. Keep physical left/right orientation consistent. Never add visible side mechanisms that are absent from the side reference. Where geometry is not visible in either reference, do not add decorative or electronic components.'
    return prompt+guidance

WEARING_REQUIREMENT=' Wearing-state requirement: use a normal fully unfolded wearing configuration. Rotate both temples outward at their real hinges so that each temple runs backward beside the head and over the corresponding ear. Never copy folded temples across the lenses, cheeks or skin. Do not paste a flat product photograph onto the face. Preserve the shape and dimensions of each rigid component; articulate only the real hinges. Keep realistic depth, nose support and ear support. Use the open side reference to determine the unfolded temple geometry.'
def wearing_prompt(prompt):
    prompt=prompt.replace('Both product views depict one rigid physical product.','Both product views depict the same articulated product. Preserve rigid parts while opening real hinges for wear.')
    return prompt if 'Wearing-state requirement:' in prompt else prompt+WEARING_REQUIREMENT
