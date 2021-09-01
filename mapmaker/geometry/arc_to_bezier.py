#===============================================================================
#
# Code (as Javascript) came from
# https://stackoverflow.com/questions/43953138/significant-error-when-approximating-elliptical-arcs-with-bezier-curves-on-canvas
# which was based on https://mortoray.com/2017/02/16/rendering-an-svg-elliptical-arc-as-bezier-curves/
#
# Original paper is at http://www.spaceroots.org/documents/ellipse/elliptical-arc.pdf
#
#===============================================================================

import math

#===============================================================================

from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point as BezierPoint

#===============================================================================

from collections import namedtuple
tuple2 = namedtuple('tuple2', 'x y')

#===============================================================================

def clamp(value, min_value, max_value):
#======================================
    return min(max(value, min_value), max_value)

def svg_angle(u, v):
#===================
    dot = u.x*v.x + u.y*v.y
    length = math.sqrt(u.x**2 + u.y**2)*math.sqrt(v.x**2 + v.y**2)
    angle = math.acos(clamp(dot/length, -1, 1))
    if (u.x*v.y - u.y*v.x) < 0:
        angle = -angle
    return angle

def elliptic_arc_point(c, r, phi, eta):
#======================================
    return tuple2(x = c.x + r.x*math.cos(phi)*math.cos(eta) - r.y*math.sin(phi)*math.sin(eta),
                  y = c.y + r.x*math.sin(phi)*math.cos(eta) + r.y*math.cos(phi)*math.sin(eta))

def elliptic_arc_derivative(r, phi, eta):
#========================================
    return tuple2(x = -r.x*math.cos(phi)*math.sin(eta) - r.y*math.sin(phi)*math.cos(eta),
                  y = -r.x*math.sin(phi)*math.sin(eta) + r.y*math.cos(phi)*math.cos(eta))

def cubic_bezier_control_points(c, r, phi, eta1, eta2):
#======================================================
    alpha = math.sin(eta2 - eta1)*(math.sqrt(4 + 3*math.pow(math.tan((eta2 - eta1)/2), 2)) - 1)/3
    P1 = elliptic_arc_point(c, r, phi, eta1)
    d1 = elliptic_arc_derivative(r, phi, eta1)
    Q1 = tuple2(P1.x + alpha*d1.x, P1.y + alpha*d1.y)
    P2 = elliptic_arc_point(c, r, phi, eta2)
    d2 = elliptic_arc_derivative(r, phi, eta2)
    Q2 = tuple2(P2.x - alpha*d2.x, P2.y - alpha*d2.y)
    return (P1, Q1, Q2, P2)

def arc_endpoints_to_centre(r, phi, flagA, flagS, p1, p2):
#=========================================================
    r_abs = tuple2(abs(r.x), abs(r.y))
    d = tuple2((p1.x - p2.x), (p1.y - p2.y))
    p = tuple2(math.cos(phi)*d.x/2 + math.sin(phi)*d.y/2,
              -math.sin(phi)*d.x/2 + math.cos(phi)*d.y/2)
    p_sq = tuple2(p.x**2, p.y**2)
    r_sq = tuple2(r_abs.x**2, r_abs.y**2)

    ratio = p_sq.x/r_sq.x + p_sq.y/r_sq.y
    if ratio > 1:
        scale = math.sqrt(ratio)
        r_abs = tuple2(scale*r_abs.x, scale*r_abs.y)
        r_sq = tuple2(r_abs.x**2, r_abs.y**2)

    dq = r_sq.x*p_sq.y + r_sq.y*p_sq.x
    pq = (r_sq.x*r_sq.y - dq)/dq
    q = math.sqrt(max(0, pq))
    if flagA == flagS:
        q = -q

    cp = tuple2(q * r_abs.x*p.y/r_abs.y,
               -q * r_abs.y*p.x/r_abs.x)
    c = tuple2(cp.x*math.cos(phi) - cp.y*math.sin(phi) + (p1.x + p2.x)/2.0,
               cp.x*math.sin(phi) + cp.y*math.cos(phi) + (p1.y + p2.y)/2.0)

    theta = svg_angle(tuple2(                   1,                     0),
                      tuple2((p.x - cp.x)/r_abs.x, ( p.y - cp.y)/r_abs.y))
    delta_theta = svg_angle(tuple2(( p.x - cp.x)/r_abs.x, ( p.y - cp.y)/r_abs.y),
                            tuple2((-p.x - cp.x)/r_abs.x, (-p.y - cp.y)/r_abs.y))
    delta_theta -= 2*math.pi*math.floor(delta_theta/(2*math.pi))
    if not flagS:
        delta_theta -= 2*math.pi

    return namedtuple('elliptical_arc',
        'centre, radii, theta, delta_theta')(c, r_abs, theta, delta_theta)

def bezier_path_from_arc_endpoints(r, phi, flagA, flagS, p1, p2, T):
#===================================================================
    arc = arc_endpoints_to_centre(r, phi, flagA, flagS, p1, p2)
    end_theta = arc.theta + arc.delta_theta
    t = arc.theta
    dt = math.pi/4
    segments = []
    while (t + dt) < end_theta:
        control_points = (BezierPoint(*T.transform_point(cp))
            for cp in cubic_bezier_control_points(arc.centre, arc.radii, phi, t, t + dt))
        segments.append(CubicBezier(*control_points))
        t += dt
    control_points = (BezierPoint(*T.transform_point(cp))
        for cp in cubic_bezier_control_points(arc.centre, arc.radii, phi, t, end_theta))
    segments.append(CubicBezier(*(tuple(control_points)[:3]), BezierPoint(*T.transform_point(p2))))
    path = BezierPath.fromSegments(segments)
    path.closed = False
    return path

#===============================================================================

if __name__ == '__main__':
    """
    rx = 25
    ry = 100
    phi = -30
    fa = 0
    fs = 1
    x = 100
    y = 200
    x1 = 150
    y1 = 175

    B<<100.00000000000023,200.0000000000004>-<85.30238404526875,174.3209908867126>-<73.82742881951359,148.34960002337942>-<68.12125626385821,127.84849286861693>>
    B<<68.12125626385821,127.84849286861693>-<62.415083708202836,107.34738571385445>-<62.933439860321826,93.95396426744364>-<69.56130919760433,90.64002959880224>>
    B<<69.56130919760433,90.64002959880224>-<76.18917853488684,87.32609493016085>-<88.3972000611082,94.3563275374012>-<103.47659532318526,110.17082333895264>>
    B<<103.47659532318526,110.17082333895264>-<118.55599058526234,125.98531914050409>-<135.3023840452683,149.3209908867118>-<150.0,175.0>>
    """

    rx = 185.684
    ry = 107.228
    phi = 0
    fa = 0
    fs = 1
    x = 0
    y = 107.228
    x1 = 185.684
    y1 = 0

    beziers = cubic_beziers_from_arc(tuple2(rx, ry), phi*math.pi/180, fa, fs, tuple2(x, y), tuple2(x1, y1))
    for bz in beziers:
        print(bz)

    """
    rx = 185.684
    ry = 107.228
    phi = 0
    fa = 0
    fs = 1
    x = 0
    y = 107.228
    x1 = 185.684
    y1 = 0

    B<<0.0,107.22800000000001>-<-6.028638799091159e-15,78.80027306807463>-<19.57643474177265,51.50779255421277>-<54.38558444215707,31.406354066928884>>
    B<<54.38558444215707,31.406354066928884>-<89.19473414254148,11.304915579644998>-<136.45642839904096,5.222088719132613e-15>-<185.684,0.0>>
    """

#===============================================================================

