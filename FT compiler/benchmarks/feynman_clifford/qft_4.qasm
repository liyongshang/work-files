OPENQASM 2.0;
include "qelib1.inc";
qreg qubits[5];
qreg cczreg[3]; // CCZReg[3]
qreg treg[1]; // TReg[1]
creg cczmeas[3];
creg tmeas[1];
h qubits[0];
cx qubits[0],qubits[1];
// Tdg injection; sampled TReg measurement = 1
cx qubits[1],treg[0];
measure treg[0] -> tmeas[0];
s qubits[1];
sdg qubits[1];
reset treg[0];
cx qubits[0],qubits[1];
// T injection; sampled TReg measurement = 0
cx qubits[0],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
// T injection; sampled TReg measurement = 0
cx qubits[1],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
cx qubits[2],qubits[0];
sdg qubits[2];
cx qubits[0],qubits[4];
cx qubits[4],qubits[2];
// T injection; sampled TReg measurement = 1
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
s qubits[2];
reset treg[0];
// Tdg injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
sdg qubits[4];
reset treg[0];
cx qubits[0],qubits[2];
cx qubits[0],qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
s qubits[2];
reset treg[0];
// Tdg injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
sdg qubits[4];
reset treg[0];
cx qubits[2],qubits[4];
h qubits[2];
// T injection; sampled TReg measurement = 1
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
s qubits[2];
reset treg[0];
h qubits[2];
cx qubits[2],qubits[4];
// Tdg injection; sampled TReg measurement = 1
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
s qubits[2];
sdg qubits[2];
reset treg[0];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
cx qubits[0],qubits[4];
cx qubits[0],qubits[2];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
// Tdg injection; sampled TReg measurement = 1
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
s qubits[2];
sdg qubits[2];
reset treg[0];
cx qubits[4],qubits[2];
cx qubits[0],qubits[4];
s qubits[2];
cx qubits[2],qubits[0];
h qubits[4];
cx qubits[0],qubits[4];
h qubits[0];
h qubits[0];
h qubits[0];
// CCZ injection; sampled CCZReg measurement = 111
cx qubits[3],cczreg[0];
cx qubits[4],cczreg[1];
cx qubits[0],cczreg[2];
measure cczreg -> cczmeas;
cz qubits[0],qubits[3];
cz qubits[0],qubits[4];
cz qubits[3],qubits[4];
z qubits[0];
z qubits[3];
z qubits[4];
reset cczreg[0];
reset cczreg[1];
reset cczreg[2];
h qubits[0];
h qubits[0];
h qubits[0];
cx qubits[0],qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
s qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
sdg qubits[4];
h qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
s qubits[4];
cx qubits[0],qubits[4];
h qubits[0];
h qubits[0];
h qubits[0];
// CCZ injection; sampled CCZReg measurement = 101
cx qubits[3],cczreg[0];
cx qubits[4],cczreg[1];
cx qubits[0],cczreg[2];
measure cczreg -> cczmeas;
cz qubits[0],qubits[4];
cz qubits[3],qubits[4];
z qubits[4];
reset cczreg[0];
reset cczreg[1];
reset cczreg[2];
h qubits[0];
h qubits[0];
h qubits[0];
cx qubits[0],qubits[4];
h qubits[1];
cx qubits[1],qubits[2];
// Tdg injection; sampled TReg measurement = 0
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
sdg qubits[2];
reset treg[0];
cx qubits[1],qubits[2];
// T injection; sampled TReg measurement = 0
cx qubits[1],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
// T injection; sampled TReg measurement = 0
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[4];
cx qubits[3],qubits[1];
sdg qubits[3];
cx qubits[1],qubits[4];
cx qubits[4],qubits[3];
// T injection; sampled TReg measurement = 1
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
s qubits[3];
reset treg[0];
// Tdg injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
sdg qubits[4];
reset treg[0];
cx qubits[1],qubits[3];
cx qubits[1],qubits[4];
// T injection; sampled TReg measurement = 0
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
// Tdg injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
sdg qubits[4];
reset treg[0];
cx qubits[3],qubits[4];
h qubits[3];
// T injection; sampled TReg measurement = 0
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
h qubits[3];
cx qubits[3],qubits[4];
// Tdg injection; sampled TReg measurement = 1
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
s qubits[3];
sdg qubits[3];
reset treg[0];
// T injection; sampled TReg measurement = 1
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
s qubits[4];
reset treg[0];
cx qubits[1],qubits[4];
cx qubits[1],qubits[3];
// T injection; sampled TReg measurement = 0
cx qubits[4],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
// Tdg injection; sampled TReg measurement = 1
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
s qubits[3];
sdg qubits[3];
reset treg[0];
cx qubits[4],qubits[3];
cx qubits[1],qubits[4];
s qubits[3];
cx qubits[3],qubits[1];
h qubits[4];
h qubits[2];
cx qubits[2],qubits[3];
// Tdg injection; sampled TReg measurement = 0
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
sdg qubits[3];
reset treg[0];
cx qubits[2],qubits[3];
// T injection; sampled TReg measurement = 1
cx qubits[2],treg[0];
measure treg[0] -> tmeas[0];
s qubits[2];
reset treg[0];
// T injection; sampled TReg measurement = 0
cx qubits[3],treg[0];
measure treg[0] -> tmeas[0];
reset treg[0];
